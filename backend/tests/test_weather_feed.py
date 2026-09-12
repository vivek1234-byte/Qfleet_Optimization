"""
The live marine feed, and the promise that it is never load-bearing.

The team brief lists venue Wi-Fi as a top risk, which is why the map carries
its own coastline. The same standard applies here: every one of these tests
exists to prove that losing the network degrades the numbers and never the
page, and that an estimated figure is never dressed up as a measured one.

The feed itself is stubbed. These assert our parsing, our fallback and our
labelling — not that Open-Meteo is up, which is not ours to test.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.data import weather_feed as wf
from backend.data.fleet_registry import LANES
from backend.data.sea_state import build_alerts


@pytest.fixture(autouse=True)
def _clean_feed():
    wf.reset_for_tests()
    yield
    wf.reset_for_tests()


def _hour() -> str:
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:00"
    )


def _stub(wave=5.2, knots=41.0, marine_ok=True, wind_ok=True, n_override=None):
    times = [_hour()]

    def fake(url, params):
        n = n_override or len(params["latitude"].split(","))
        if "marine" in url:
            if not marine_ok:
                return None
            return [
                {"hourly": {"time": times, "wave_height": [wave], "swell_wave_height": [wave * 0.6],
                            "wind_wave_height": [wave * 0.4], "wave_period": [10.0]}}
                for _ in range(n)
            ]
        if not wind_ok:
            return None
        return [
            {"hourly": {"time": times, "wind_speed_10m": [knots], "wind_gusts_10m": [knots * 1.4]}}
            for _ in range(n)
        ]

    return fake


class TestBeaufortFromWind:
    @pytest.mark.parametrize(
        "knots,force",
        [(0, 0), (2, 1), (5, 2), (9, 3), (15, 4), (20, 5), (26, 6), (32, 7), (38, 8), (45, 9), (70, 12)],
    )
    def test_matches_the_standard_scale(self, knots, force):
        assert wf.beaufort_from_knots(knots) == force


class TestFallback:
    def test_no_network_still_produces_alerts(self, monkeypatch):
        """The whole point. An unreachable feed must not break the feature."""
        monkeypatch.setattr(wf, "_get_json", lambda url, params: None)
        payload = build_alerts(LANES, None, live=True)
        assert payload["live"]["mode"] == "climatology"
        assert payload["lanes_observed"] == 0
        assert payload["counts"]["total"] >= 0
        assert all(a["source"] == "climatology" for a in payload["alerts"])

    def test_the_basis_admits_it_is_estimated(self, monkeypatch):
        monkeypatch.setattr(wf, "_get_json", lambda url, params: None)
        assert "not measured" in build_alerts(LANES, None, live=True)["basis"].lower()

    def test_the_circuit_stops_calling_a_dead_feed(self):
        """
        An offline venue must not pay the HTTP timeout on every request. After
        FAILURE_THRESHOLD failures the breaker opens and calls stop entirely.
        """
        calls = {"n": 0}

        def always_down(*_args, **_kwargs):
            calls["n"] += 1
            raise OSError("network down")

        original = wf.urllib.request.urlopen
        wf.urllib.request.urlopen = always_down
        try:
            for _ in range(8):
                wf.fetch_marine([(19.0, 72.9)])
            before = calls["n"]
            wf.fetch_marine([(19.0, 72.9)])
            assert calls["n"] == before, "breaker was open but a call still went out"
        finally:
            wf.urllib.request.urlopen = original

        assert calls["n"] <= wf.FAILURE_THRESHOLD * 2, (
            f"kept dialling a dead feed: {calls['n']} attempts"
        )

    @pytest.mark.parametrize("body", [{"unexpected": True}, {"hourly": {}}, {"hourly": {"time": []}}])
    def test_a_body_without_waves_yields_no_reading(self, monkeypatch, body):
        """
        A 200 with nothing usable in it must not become a fabricated sea
        state. The point is per-point None, so the lane falls back rather
        than reporting a wave height nobody measured.
        """
        monkeypatch.setattr(wf, "_get_json", lambda url, params: body)
        assert wf.fetch_marine([(19.0, 72.9)]) == [None]

    def test_a_lane_with_no_reading_falls_back_and_says_so(self, monkeypatch):
        monkeypatch.setattr(wf, "_get_json", lambda url, params: {"hourly": {"time": []}})
        payload = build_alerts(LANES, None, live=True)
        assert payload["live"]["mode"] == "climatology"
        assert all(a["source"] == "climatology" for a in payload["alerts"])


class TestLivePath:
    def test_observed_readings_replace_the_estimate(self, monkeypatch):
        monkeypatch.setattr(wf, "_get_json", _stub(wave=5.2, knots=41.0))
        payload = build_alerts(LANES, None, live=True)
        assert payload["live"]["mode"] == "observed"
        assert payload["lanes_observed"] == payload["lanes_assessed"]
        for alert in payload["alerts"]:
            assert alert["source"] == "observed"
            # The model's own wave height, not the WMO band for the force.
            assert alert["significant_wave_m"] == 5.2
            assert alert["wind_knots"] == 41.0

    def test_a_real_gale_reaches_high_impact(self, monkeypatch):
        monkeypatch.setattr(wf, "_get_json", _stub(wave=5.2, knots=41.0))
        payload = build_alerts(LANES, None, live=True)
        assert payload["worst_severity"] == "high"
        assert any("gale" in a["detail"].lower() for a in payload["alerts"])

    def test_calm_observed_water_raises_nothing(self, monkeypatch):
        """A live feed that says the sea is flat must clear the dot."""
        monkeypatch.setattr(wf, "_get_json", _stub(wave=0.4, knots=6.0))
        payload = build_alerts(LANES, None, live=True)
        assert payload["counts"]["total"] == 0
        assert payload["worst_severity"] is None

    def test_wind_missing_falls_back_to_wave_height(self, monkeypatch):
        monkeypatch.setattr(wf, "_get_json", _stub(wave=5.2, wind_ok=False))
        sample = wf.fetch_marine([(19.0, 72.9)])[0]
        assert sample["beaufort_basis"] == "wave height"
        assert sample["wind_knots"] is None
        assert sample["beaufort"] >= 7

    def test_partial_coverage_is_reported_as_mixed(self, monkeypatch):
        """Half the lanes answering must upgrade half, not all or none."""
        times = [_hour()]

        def half(url, params):
            n = len(params["latitude"].split(","))
            body = lambda ok: (
                {"hourly": {"time": times, "wave_height": [5.2], "swell_wave_height": [3.0],
                            "wind_wave_height": [2.0], "wave_period": [10.0]}}
                if ok else {}
            )
            if "marine" in url:
                return [body(i % 2 == 0) for i in range(n)]
            return [
                {"hourly": {"time": times, "wind_speed_10m": [41.0], "wind_gusts_10m": [55.0]}}
                for _ in range(n)
            ]

        monkeypatch.setattr(wf, "_get_json", half)
        payload = build_alerts(LANES, None, live=True)
        assert payload["live"]["mode"] == "mixed"
        assert 0 < payload["lanes_observed"] < payload["lanes_assessed"]
        sources = {a["source"] for a in payload["alerts"]}
        assert sources == {"observed", "climatology"} or len(sources) == 1

    def test_an_outlook_month_never_claims_to_be_observed(self, monkeypatch):
        """No feed forecasts July from September; an outlook is climatology."""
        monkeypatch.setattr(wf, "_get_json", _stub())
        payload = build_alerts(LANES, 7, live=False)
        assert payload["live"]["mode"] == "climatology"
        assert all(a["source"] == "climatology" for a in payload["alerts"])

    def test_tides_are_still_not_invented_with_a_live_feed(self, monkeypatch):
        monkeypatch.setattr(wf, "_get_json", _stub())
        payload = build_alerts(LANES, None, live=True)
        assert "not modelled" in payload["not_modelled"]["tides"].lower()
        assert "tide" not in str(payload["alerts"]).lower()


class TestEndpointContract:
    def test_live_can_be_turned_off(self, client):
        response = client.get("/api/regulatory/alerts", params={"live": "false"})
        assert response.status_code == 200
        assert response.json()["live"]["mode"] == "climatology"

    def test_an_outlook_is_forced_to_climatology(self, client):
        body = client.get("/api/regulatory/alerts", params={"month": 7, "live": "true"}).json()
        assert body["live"]["mode"] == "climatology"

    def test_the_payload_always_declares_its_mode(self, client):
        body = client.get("/api/regulatory/alerts").json()
        assert body["live"]["mode"] in {"observed", "mixed", "climatology"}
        assert "attribution" in body["live"]
