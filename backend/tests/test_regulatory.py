"""
Tests for the regulatory layer: route geometry, emission control areas,
carbon intensity and seasonal weather.

The CII tests pin the published MEPC constants rather than whatever the code
happens to produce, so a typo in a reference line is a failure and not a
slightly different rating.
"""
from __future__ import annotations

import math

import pytest

from backend.data.carbon_intensity import (
    CII_SHIP_TYPES,
    REDUCTION_FACTOR_PCT,
    assess_fleet,
    assess_voyage,
    band_boundaries,
    capacity_for,
    rate,
    reduction_factor_pct,
    reference_cii,
    required_cii,
    ship_type_for,
)
from backend.data.fleet_registry import LANES, VESSELS
from backend.data.fuel_database import get_all_fuels, get_fuel
from backend.data.sea_routes import (
    ECA_ZONES,
    LANE_ECA,
    PORT_POSITIONS,
    eca_fraction_for,
    haversine_nm,
    lane_geometry,
    lane_points,
    point_in_polygon,
    zone_containing,
)
from backend.data.seasonality import (
    BASIN_MONTHLY_FACTOR,
    monthly_profile,
    season_label,
    seasonal_factor,
)
from backend.optimization.fleet_problem import (
    ECA_SULPHUR_LIMIT_PCT,
    FleetOptimizationProblem,
)


# ---------------------------------------------------------------------------
# Route geometry
# ---------------------------------------------------------------------------
class TestSeaRoutes:
    def test_every_lane_has_a_drawable_path(self):
        for lane in LANES:
            points = lane_points(lane)
            assert len(points) >= 2, f"{lane.name} has no geometry"

    def test_every_endpoint_is_a_known_port(self):
        for lane in LANES:
            assert lane.origin in PORT_POSITIONS, lane.origin
            assert lane.destination in PORT_POSITIONS, lane.destination

    def test_lane_distances_match_routing(self):
        """
        The registry's distance must stay within 2% of the routed polyline.

        This is the test that stops someone moving a waypoint and leaving the
        distance table saying something else. It is also what makes the claim
        "these are sea distances, not great-circle distances" checkable.
        """
        for lane in LANES:
            points = lane_points(lane)
            routed = sum(haversine_nm(points[i - 1], points[i]) for i in range(1, len(points)))
            drift = abs(routed - lane.distance_nm) / lane.distance_nm
            assert drift < 0.02, (
                f"{lane.name}: registry says {lane.distance_nm} nm, "
                f"the routed path is {routed:.0f} nm ({drift:.1%} out)"
            )

    def test_geometry_cumulative_sums_to_registry_distance(self):
        for lane in LANES:
            g = lane_geometry(lane)
            assert g["cumulative_nm"][0] == 0.0
            assert g["cumulative_nm"][-1] == pytest.approx(lane.distance_nm, rel=1e-3)

    def test_suez_lanes_pass_through_the_canal(self):
        """Rotterdam must go via Suez, not across Africa."""
        for name in ("Mundra – Rotterdam", "JNPT – Felixstowe"):
            lane = next(l for l in LANES if l.name == name)
            points = lane_points(lane)
            assert any(
                29.0 < lat < 32.0 and 31.5 < lon < 33.0 for lat, lon in points
            ), f"{name} does not transit the Suez Canal"

    def test_east_bound_lanes_use_malacca(self):
        for name in ("Mundra – Shanghai", "Paradip – Qingdao", "Mormugao – Jinzhou"):
            lane = next(l for l in LANES if l.name == name)
            points = lane_points(lane)
            assert any(
                0.5 < lat < 6.0 and 97.0 < lon < 105.0 for lat, lon in points
            ), f"{name} does not transit the Malacca Strait"

    def test_colombo_rounds_sri_lanka(self):
        """Adam's Bridge closes the Palk Strait, so nothing may cut inside."""
        lane = next(l for l in LANES if l.name == "Chennai – Colombo")
        for lat, lon in lane_points(lane):
            inside_island = 6.2 < lat < 9.6 and 79.9 < lon < 81.7
            assert not inside_island, f"waypoint ({lat}, {lon}) is on Sri Lanka"


# ---------------------------------------------------------------------------
# Emission control areas
# ---------------------------------------------------------------------------
class TestEcaZones:
    def test_zones_are_closed_polygons_with_a_tight_sulphur_cap(self):
        for zone in ECA_ZONES:
            assert len(zone.polygon) >= 4, zone.name
            assert zone.sulphur_limit_pct == pytest.approx(0.10)

    @pytest.mark.parametrize(
        "point,expected",
        [
            ((35.0, 18.0), "Mediterranean SECA"),  # Ionian Sea
            ((55.0, 3.5), "North Sea SECA"),  # southern North Sea
            ((58.0, 20.0), "Baltic SECA"),  # central Baltic
            ((15.0, 65.0), None),  # Arabian Sea
            ((1.3, 103.8), None),  # Singapore
        ],
    )
    def test_point_in_zone(self, point, expected):
        zone = zone_containing(point)
        assert (zone.short_name if zone else None) == expected

    def test_point_in_polygon_handles_a_square(self):
        square = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]
        assert point_in_polygon((5.0, 5.0), square)
        assert not point_in_polygon((15.0, 5.0), square)
        assert not point_in_polygon((5.0, -1.0), square)

    def test_only_the_european_lanes_are_eca_exposed(self):
        exposed = {name for name, p in LANE_ECA.items() if p["eca_fraction"] > 0}
        assert exposed == {"Mundra – Rotterdam", "JNPT – Felixstowe"}

    def test_european_lanes_are_roughly_a_third_controlled(self):
        for name in ("Mundra – Rotterdam", "JNPT – Felixstowe"):
            fraction = eca_fraction_for(name)
            assert 0.25 < fraction < 0.50, f"{name}: {fraction:.1%}"

    def test_unknown_lane_has_no_exposure(self):
        assert eca_fraction_for("Nowhere – Nothing") == 0.0


class TestFuelSulphur:
    def test_compliance_follows_the_eca_cap(self):
        for fuel in get_all_fuels():
            assert fuel.eca_compliant == (fuel.sulphur_pct <= ECA_SULPHUR_LIMIT_PCT + 1e-9)

    def test_residual_fuels_are_not_eca_compliant(self):
        assert not get_fuel("HFO").eca_compliant
        assert not get_fuel("VLSFO").eca_compliant

    def test_distillate_and_alternatives_are_compliant(self):
        for name in ("MGO", "LNG", "Methanol", "Ammonia", "Hydrogen"):
            assert get_fuel(name).eca_compliant, name

    def test_vlsfo_meets_the_global_cap_but_not_the_eca_cap(self):
        assert get_fuel("VLSFO").sulphur_pct == pytest.approx(0.50)


class TestEcaCostEffect:
    def test_switching_makes_a_controlled_lane_dearer_for_a_dirty_fuel(self):
        """
        Same ship, same lane, same speed: HFO costs more once a third of the
        voyage has to be sailed on distillate. Without that premium the
        optimiser would happily burn residual fuel through the Channel.
        """
        from backend.optimization.fleet_problem import RouteProfile, VesselProfile

        vessel = VesselProfile(
            vessel_id=0,
            name="Test",
            vessel_type="Container",
            dwt=90_000,
            rated_power_kw=40_000,
            design_speed_knots=20.0,
            min_speed_knots=12.0,
            max_speed_knots=22.0,
            cargo_load_pct=80.0,
            hotel_load_kw=1_200.0,
            port_hours=40.0,
            tank_volume_m3=7_000.0,
            home_port="JNPT",
            built=2018,
        )

        def cost_on(eca_fraction: float, fuel: str) -> float:
            route = RouteProfile(
                route_id=0,
                name="Test lane",
                distance_nm=6_000.0,
                weather_beaufort=4.0,
                demand_tons=1.0,
                max_transit_days=40.0,
                eca_fraction=eca_fraction,
            )
            problem = FleetOptimizationProblem(
                vessels=[vessel], routes=[route], fuel_types=[fuel], enforce_demand=False
            )
            x = problem.baseline_vector()
            x[1] = 16.0  # same speed in both cases
            return problem.describe_solution(x)["objectives"]["operational_cost_usd"]

        clean_water = cost_on(0.0, "HFO")
        controlled = cost_on(0.40, "HFO")
        assert controlled > clean_water * 1.02

        # A fuel already under the cap pays nothing extra.
        assert cost_on(0.40, "MGO") == pytest.approx(cost_on(0.0, "MGO"))


# ---------------------------------------------------------------------------
# Carbon intensity
# ---------------------------------------------------------------------------
class TestCarbonIntensity:
    def test_published_reference_line_constants(self):
        """MEPC.353(78) values. A typo here silently misrates the whole fleet."""
        assert (CII_SHIP_TYPES["Bulk Carrier"].a, CII_SHIP_TYPES["Bulk Carrier"].c) == (4745.0, 0.622)
        assert (CII_SHIP_TYPES["Tanker"].a, CII_SHIP_TYPES["Tanker"].c) == (5247.0, 0.610)
        assert (CII_SHIP_TYPES["Container"].a, CII_SHIP_TYPES["Container"].c) == (1984.0, 0.489)

    def test_published_rating_boundaries(self):
        """MEPC.354(78) dd vectors."""
        assert CII_SHIP_TYPES["Bulk Carrier"].dd == (0.86, 0.94, 1.06, 1.18)
        assert CII_SHIP_TYPES["Tanker"].dd == (0.82, 0.93, 1.08, 1.28)
        assert CII_SHIP_TYPES["Container"].dd == (0.83, 0.94, 1.07, 1.19)

    def test_reduction_factors(self):
        assert REDUCTION_FACTOR_PCT == {2023: 5.0, 2024: 7.0, 2025: 9.0, 2026: 11.0}
        assert reduction_factor_pct(2026) == 11.0
        # Beyond 2026 is an extrapolation of the agreed 2%-a-year trend.
        assert reduction_factor_pct(2028) == pytest.approx(15.0)
        assert reduction_factor_pct(2019) == 0.0

    def test_container_capacity_is_seventy_percent_of_deadweight(self):
        assert capacity_for(CII_SHIP_TYPES["Container"], 100_000) == pytest.approx(70_000)
        assert capacity_for(CII_SHIP_TYPES["Tanker"], 100_000) == pytest.approx(100_000)

    def test_bulk_carrier_capacity_is_capped(self):
        capped = capacity_for(CII_SHIP_TYPES["Bulk Carrier"], 400_000)
        assert capped == pytest.approx(279_000)

    def test_reference_line_formula(self):
        st = CII_SHIP_TYPES["Tanker"]
        expected = st.a * (100_000 ** -st.c)
        assert reference_cii(st, 100_000) == pytest.approx(expected)

    def test_required_line_applies_the_reduction_factor(self):
        st = CII_SHIP_TYPES["Tanker"]
        assert required_cii(st, 100_000, 2026) == pytest.approx(
            reference_cii(st, 100_000) * 0.89
        )

    @pytest.mark.parametrize(
        "ratio,expected",
        [(0.50, "A"), (0.86, "A"), (0.90, "B"), (1.00, "C"), (1.10, "D"), (1.50, "E")],
    )
    def test_rating_bands_for_a_bulk_carrier(self, ratio, expected):
        st = CII_SHIP_TYPES["Bulk Carrier"]
        assert rate(ratio * 100.0, 100.0, st) == expected

    def test_boundaries_are_monotonic(self):
        b = band_boundaries(CII_SHIP_TYPES["Container"], 92_000, 2026)
        assert b["A_B"] < b["B_C"] < b["C_D"] < b["D_E"]

    def test_attained_cii_is_grams_per_dwt_nautical_mile(self):
        # 100 t CO2, 50,000 dwt tanker, 1,000 nm -> 100e6 g / 50e6 dwt-nm = 2.0
        r = assess_voyage(
            vessel_name="T", vessel_type="Tanker", dwt=50_000, co2_tons=100, distance_nm=1_000
        )
        assert r["attained_cii"] == pytest.approx(2.0)
        assert r["unit"] == "gCO2 per dwt-nautical mile"

    def test_burning_less_improves_the_rating(self):
        common = dict(vessel_name="T", vessel_type="Container", dwt=92_000, distance_nm=2_520)
        dirty = assess_voyage(co2_tons=1_400, **common)
        clean = assess_voyage(co2_tons=500, **common)
        assert clean["attained_cii"] < dirty["attained_cii"]
        assert "ABCDE".index(clean["rating"]) < "ABCDE".index(dirty["rating"])

    def test_unknown_vessel_type_is_reported_not_guessed(self):
        r = assess_voyage(
            vessel_name="X", vessel_type="Submarine", dwt=1_000, co2_tons=1, distance_nm=1
        )
        assert r["rated"] is False and "reason" in r

    def test_zero_distance_is_rejected_rather_than_dividing_by_zero(self):
        r = assess_voyage(
            vessel_name="X", vessel_type="Tanker", dwt=1_000, co2_tons=1, distance_nm=0
        )
        assert r["rated"] is False

    def test_fleet_assessment_counts_and_flags(self):
        report = assess_fleet(
            [
                dict(vessel_name="good", vessel_type="Tanker", dwt=100_000, co2_tons=50, distance_nm=5_000),
                dict(vessel_name="bad", vessel_type="Tanker", dwt=100_000, co2_tons=5_000, distance_nm=5_000),
            ]
        )
        assert report["rated_count"] == 2
        assert sum(report["distribution"].values()) == 2
        assert [v["vessel_name"] for v in report["at_risk"]] == ["bad"]
        assert report["caveats"], "the annual-vs-voyage caveat must be surfaced"

    def test_every_registry_vessel_can_be_rated(self):
        for vessel in VESSELS:
            assert ship_type_for(vessel.vessel_type) is not None, vessel.vessel_type


# ---------------------------------------------------------------------------
# Seasonality
# ---------------------------------------------------------------------------
class TestSeasonality:
    def test_every_lane_basin_is_known(self):
        for lane in LANES:
            for basin, _ in lane.basins:
                assert basin in BASIN_MONTHLY_FACTOR, f"{lane.name}: unknown basin {basin}"

    def test_basin_shares_sum_to_one(self):
        for lane in LANES:
            assert sum(w for _, w in lane.basins) == pytest.approx(1.0), lane.name

    def test_arabian_sea_peaks_in_the_south_west_monsoon(self):
        factors = BASIN_MONTHLY_FACTOR["Arabian Sea"]
        peak_month = factors.index(max(factors)) + 1
        assert peak_month in (6, 7, 8), f"monsoon peak landed in month {peak_month}"

    def test_north_atlantic_peaks_in_winter(self):
        factors = BASIN_MONTHLY_FACTOR["NE Atlantic"]
        peak_month = factors.index(max(factors)) + 1
        assert peak_month in (12, 1, 2)

    def test_blended_factor_is_the_weighted_mean(self):
        basins = (("Arabian Sea", 0.5), ("Red Sea", 0.5))
        expected = (
            BASIN_MONTHLY_FACTOR["Arabian Sea"][6] + BASIN_MONTHLY_FACTOR["Red Sea"][6]
        ) / 2
        assert seasonal_factor(basins, 7) == pytest.approx(expected)

    def test_month_wraps_rather_than_raising(self):
        assert seasonal_factor((("Arabian Sea", 1.0),), 13) == pytest.approx(
            seasonal_factor((("Arabian Sea", 1.0),), 1)
        )

    def test_no_basins_is_neutral(self):
        assert seasonal_factor((), 7) == 1.0

    def test_season_labels(self):
        assert season_label(7) == "South-west monsoon"
        assert season_label(1) == "North-east monsoon"

    def test_monthly_profile_covers_the_year(self):
        profile = monthly_profile((("Bay of Bengal", 1.0),))
        assert [p["month"] for p in profile] == list(range(1, 13))


class TestSeasonalOptimisation:
    def test_the_monsoon_costs_fuel(self):
        """
        The same fleet on the same lanes burns more in July than in March.
        If this ever stops being true the weather model has been disconnected.
        """
        def fuel_in(month):
            problem = FleetOptimizationProblem(n_vessels=8, n_routes=5, seed=11, month=month)
            plan = problem.describe_solution(problem.baseline_vector())
            return plan["objectives"]["fuel_consumption_tons"]

        assert fuel_in(7) > fuel_in(3) * 1.05

    def test_annual_mean_leaves_the_weather_untouched(self):
        problem = FleetOptimizationProblem(n_vessels=5, n_routes=3, seed=5)
        for route in problem.routes:
            assert route.season_factor == 1.0
            assert route.weather_beaufort == pytest.approx(route.base_beaufort)

    def test_speed_cap_binds_without_making_the_problem_infeasible(self):
        cap = 13.0
        capped = FleetOptimizationProblem(n_vessels=6, n_routes=4, seed=9, speed_cap_knots=cap)
        plan = capped.describe_solution(capped.baseline_vector())
        # Every vessel sits at or under the cap, except where the cap is below
        # its minimum manoeuvring speed — there the minimum wins, because a cap
        # should slow a fleet down, not make the problem unsolvable.
        for assignment, vessel in zip(plan["assignments"], capped.vessels):
            ceiling = max(cap, vessel.min_speed_knots) + 0.15
            assert assignment["speed_knots"] <= ceiling, assignment["vessel_name"]

        uncapped = FleetOptimizationProblem(n_vessels=6, n_routes=4, seed=9)
        assert plan["average_speed_knots"] < uncapped.describe_solution(
            uncapped.baseline_vector()
        )["average_speed_knots"]

        # A cap below every minimum must not invert the bounds.
        floor = FleetOptimizationProblem(n_vessels=6, n_routes=4, seed=9, speed_cap_knots=5.0)
        assert bool((floor._vmax > floor._vmin).all())

    def test_plan_carries_compliance_and_season_blocks(self):
        problem = FleetOptimizationProblem(n_vessels=6, n_routes=4, seed=7, month=7)
        plan = problem.describe_solution(problem.baseline_vector())
        assert plan["season"]["month"] == 7
        assert plan["season"]["label"] == "South-west monsoon"
        assert plan["compliance"]["eca_switch_fuel"] == "MGO"
        assert set(plan["compliance"]["cii"]["distribution"]) == set("ABCDE")
        for assignment in plan["assignments"]:
            assert "cii" in assignment and "eca_fraction" in assignment
