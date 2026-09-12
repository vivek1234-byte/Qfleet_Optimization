"""
Sea-state alerts.

The tests that matter here are the ones about honesty. The alert engine sits
on indicative climatology, so what has to hold is that it never dresses that
up as something it is not: no tide warning from data that does not exist, no
"severe weather" label on a fresh breeze, and no alert whose absolute force
is hidden behind a scary percentage.
"""
from __future__ import annotations

import pytest

from backend.data.fleet_registry import LANES
from backend.data.sea_state import (
    BEAUFORT_SCALE,
    HIGH_DEVIATION,
    SEVERITY_LABEL,
    build_alerts,
    describe_force,
    lane_sea_state,
)


class TestBeaufortTable:
    def test_wave_height_rises_with_force(self):
        heights = [BEAUFORT_SCALE[f][1] for f in range(13)]
        assert heights == sorted(heights)

    def test_force_is_clamped_not_crashed(self):
        assert describe_force(-3) == BEAUFORT_SCALE[0]
        assert describe_force(99) == BEAUFORT_SCALE[12]


class TestLaneSeaState:
    @pytest.mark.parametrize("month", range(1, 13))
    def test_every_lane_resolves_in_every_month(self, month):
        for lane in LANES:
            state = lane_sea_state(lane, month)
            assert 0 <= state["beaufort"] <= 12
            assert state["significant_wave_m"] >= 0
            assert state["description"]

    def test_the_monsoon_shows_up_on_the_arabian_sea(self):
        """July must be rougher than April on a lane that is all Arabian Sea."""
        lane = next(l for l in LANES if l.basins == (("Arabian Sea", 1.0),))
        assert lane_sea_state(lane, 7)["beaufort"] > lane_sea_state(lane, 4)["beaufort"]


class TestAlerts:
    def test_july_flags_more_than_april(self):
        """If the monsoon does not move the count, the feature is decoration."""
        assert build_alerts(LANES, 7)["counts"]["total"] > build_alerts(LANES, 4)["counts"]["total"]

    def test_alerts_are_ordered_worst_first(self):
        rank = {"high": 0, "moderate": 1, "watch": 2}
        levels = [rank[a["severity"]] for a in build_alerts(LANES, 7)["alerts"]]
        assert levels == sorted(levels)

    @pytest.mark.parametrize("month", range(1, 13))
    def test_every_alert_carries_its_absolute_conditions(self, month):
        """
        A percentage on its own is alarmist and a force on its own is bland.
        Both have to be on every alert or the label can be misread.
        """
        for alert in build_alerts(LANES, month)["alerts"]:
            assert "force" in alert["detail"]
            assert "m seas" in alert["detail"]
            assert alert["severity_label"] in SEVERITY_LABEL.values()

    @pytest.mark.parametrize("month", range(1, 13))
    def test_no_alert_claims_weather_the_data_does_not_show(self, month):
        """
        Severity is named for operational impact, never for the weather. A
        fresh breeze must not be able to print the word "gale" anywhere.
        """
        for alert in build_alerts(LANES, month)["alerts"]:
            text = f"{alert['severity_label']} {alert['headline']} {alert['detail']}".lower()
            if alert["beaufort"] < 8:
                assert "gale" not in text
            if alert["beaufort"] < 10:
                assert "storm" not in text and "hurricane" not in text

    def test_tides_are_declared_unavailable_rather_than_invented(self):
        payload = build_alerts(LANES, 7)
        assert "tides" in payload["not_modelled"]
        assert "not modelled" in payload["not_modelled"]["tides"].lower()
        blob = str(payload["alerts"]).lower()
        assert "tide" not in blob, "an alert mentioned tides, which are not modelled"

    def test_the_payload_says_the_figures_are_indicative(self):
        assert "not measured" in build_alerts(LANES, 7)["basis"].lower()

    def test_worst_severity_matches_the_alerts(self):
        for month in range(1, 13):
            payload = build_alerts(LANES, month)
            if payload["alerts"]:
                assert payload["worst_severity"] == payload["alerts"][0]["severity"]
            else:
                assert payload["worst_severity"] is None

    def test_a_lane_well_over_its_mean_is_high_impact(self):
        for alert in build_alerts(LANES, 7)["alerts"]:
            if alert["vs_annual_pct"] >= HIGH_DEVIATION * 100:
                assert alert["severity"] == "high"

    def test_month_is_clamped(self):
        assert build_alerts(LANES, 0)["month"] == 1
        assert build_alerts(LANES, 99)["month"] == 12


class TestEndpoint:
    def test_any_signed_in_user_gets_the_warning(self, client):
        """Reference data — the dot belongs in the header for everyone."""
        response = client.get("/api/regulatory/alerts")
        assert response.status_code == 200
        body = response.json()
        assert "alerts" in body and "counts" in body and "not_modelled" in body

    def test_month_query_is_validated(self, client):
        assert client.get("/api/regulatory/alerts", params={"month": 7}).status_code == 200
        assert client.get("/api/regulatory/alerts", params={"month": 13}).status_code == 422
