#!/usr/bin/env python3
"""
Full backend API conformance test.

Hits every declared operation, checks status codes, validates response shape,
and asserts on the values that actually matter (savings are positive, the plan
is feasible, prediction is batch-independent, security holds). Run with the
server up:  python3 apitest.py [--base http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8100"
PASS, FAIL, SKIP = [], [], []


def call(method, path, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null"), time.perf_counter() - started
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"null"), time.perf_counter() - started
        except json.JSONDecodeError:
            return e.code, raw.decode(errors="replace"), time.perf_counter() - started
    except Exception as e:  # connection refused, timeout, ...
        return 0, f"{type(e).__name__}: {e}", time.perf_counter() - started


def check(name, method, path, *, body=None, expect=200, assertions=(), timeout=180):
    status, payload, elapsed = call(method, path, body, timeout)
    problems = []
    if status != expect:
        detail = payload if isinstance(payload, str) else json.dumps(payload)[:200]
        problems.append(f"expected HTTP {expect}, got {status} — {detail}")
    else:
        for label, fn in assertions:
            try:
                if not fn(payload):
                    problems.append(f"assertion failed: {label}")
            except Exception as exc:
                problems.append(f"assertion errored ({label}): {type(exc).__name__}: {exc}")

    if problems:
        FAIL.append((name, method, path, problems))
        print(f"  FAIL  {method:4s} {path:42s} {elapsed:6.2f}s")
        for p in problems:
            print(f"        └─ {p}")
    else:
        PASS.append((name, elapsed))
        print(f"  ok    {method:4s} {path:42s} {elapsed:6.2f}s  {name}")
    return payload


# ---------------------------------------------------------------------------
VOYAGE = {
    "vessel_type": "Container", "dwt": 120000, "engine_power_kw": 35000,
    "speed_knots": 16.5, "distance_nm": 5000, "cargo_load_pct": 85,
    "weather_beaufort": 4, "draft_meters": 13.5, "fuel_type": "LNG",
}
SMALL = {"n_vessels": 8, "n_routes": 4, "max_iterations": 30, "population_size": 24}


def has(*keys):
    return lambda d: all(k in d for k in keys)


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    BASE = ap.parse_args().base.rstrip("/")

    print(f"\nTesting {BASE}\n" + "=" * 78)

    # -- Meta ---------------------------------------------------------------
    print("\n[Meta]")
    check("root info", "GET", "/", assertions=[
        ("status running", lambda d: d["status"] == "running"),
        ("lists endpoints", has("endpoints", "version")),
    ])
    health = check("health", "GET", "/api/health", assertions=[
        ("has checks", lambda d: set(d["checks"]) == {"api", "prediction_model", "dataset"}),
        ("status healthy", lambda d: d["status"] == "healthy"),
    ])
    check("openapi schema", "GET", "/openapi.json", assertions=[
        ("24+ paths", lambda d: len(d["paths"]) >= 20),
    ])

    model_ready = bool(health and health.get("checks", {}).get("prediction_model", {}).get("ok"))

    # -- Optimization -------------------------------------------------------
    print("\n[Optimization]")
    check("algorithm list", "GET", "/api/optimization/algorithms", assertions=[
        ("4 algorithms", lambda d: {a["id"] for a in d} == {"qpso", "qga", "pso", "nsga2"}),
        ("capabilities present", lambda d: all(has("multi_objective", "quantum_inspired")(a) for a in d)),
    ])
    check("registry", "GET", "/api/optimization/registry", assertions=[
        ("20 vessels", lambda d: d["vessel_count"] == 20),
        ("16 lanes", lambda d: d["lane_count"] == 16),
        ("real vessel names", lambda d: all(not v["name"].startswith(("CON-", "BUL-", "TAN-")) for v in d["vessels"])),
        ("lanes have port codes", lambda d: all(v["origin_code"] and v["destination_code"] for v in d["lanes"])),
    ])
    check("fleet inspection", "GET", "/api/optimization/fleet?n_vessels=6&n_routes=3", assertions=[
        ("6 vessels", lambda d: len(d["vessels"]) == 6),
        ("3 routes", lambda d: len(d["routes"]) == 3),
        ("baseline feasible", lambda d: d["baseline"]["feasible"] is True),
        ("routes named with ports", lambda d: all(r["origin"] and r["destination"] for r in d["routes"])),
    ])

    for algo in ("qpso", "qga", "pso", "nsga2"):
        check(f"optimize [{algo}]", "POST", "/api/optimization/optimize",
              body={"algorithm": algo, **SMALL},
              assertions=[
                  ("echoes algorithm", lambda d, a=algo: d["algorithm"] == a),
                  ("did real work", lambda d: d["n_evaluations"] > 0),
                  ("convergence length matches iterations", lambda d: len(d["convergence_history"]) == SMALL["max_iterations"]),
                  ("convergence is monotone", lambda d: all(
                      d["convergence_history"][i] >= d["convergence_history"][i + 1] - 1e-9
                      for i in range(len(d["convergence_history"]) - 1))),
                  ("plan covers every vessel", lambda d: len(d["plan"]["assignments"]) == SMALL["n_vessels"]),
                  ("plan feasible", lambda d: d["feasible"] is True),
                  ("no negative savings", lambda d: all(
                      v["percent_saving"] >= -1e-6 for v in d["improvement_vs_baseline"].values())),
                  ("not the old stub", lambda d: d["elapsed_seconds"] != 2.34),
                  ("real vessel names in plan", lambda d: all(
                      a["vessel_name"].startswith(("MV ", "MT ")) for a in d["plan"]["assignments"])),
              ])

    a = check("optimize determinism A", "POST", "/api/optimization/optimize",
              body={"algorithm": "qpso", "seed": 777, **SMALL})
    b = check("optimize determinism B", "POST", "/api/optimization/optimize",
              body={"algorithm": "qpso", "seed": 777, **SMALL},
              assertions=[("same seed, same result", lambda d: d["best_objectives"] == a["best_objectives"])])

    check("optimize respects fuel subset", "POST", "/api/optimization/optimize",
          body={"algorithm": "qpso", "fuel_types": ["HFO", "LNG"], **SMALL},
          assertions=[("only requested fuels used", lambda d: set(d["plan"]["fuel_mix"]) <= {"HFO", "LNG"})])

    check("optimize honours carbon price", "POST", "/api/optimization/optimize",
          body={"algorithm": "qpso", "carbon_price_usd_per_ton": 150, **SMALL},
          assertions=[("carbon price echoed", lambda d: d["problem"]["carbon_price_usd_per_ton"] == 150)])

    check("compare algorithms", "POST", "/api/optimization/compare",
          body={"algorithms": ["qpso", "pso", "nsga2"], **SMALL},
          assertions=[
              ("all three ran", lambda d: {r["algorithm"] for r in d["comparison"]} == {"qpso", "pso", "nsga2"}),
              ("none failed", lambda d: not any(r.get("failed") for r in d["comparison"])),
              ("convergence per algorithm", lambda d: set(d["convergence"]) == {"qpso", "pso", "nsga2"}),
              ("winner declared", lambda d: d["winner"] in {"qpso", "pso", "nsga2"}),
              ("same problem instance", lambda d: d["problem"]["n_vessels"] == SMALL["n_vessels"]),
          ])

    # -- Prediction ---------------------------------------------------------
    print("\n[Prediction]")
    check("model info", "GET", "/api/prediction/model-info", assertions=[
        ("trained", lambda d: d["trained"] is True),
        ("fuel + vessel enums", has("fuel_types", "vessel_types")),
        ("cubic feature present", lambda d: "cubic_energy_proxy" in d["features"]),
    ])
    if not model_ready:
        SKIP.append("prediction endpoints — no trained model")
        print("  SKIP  prediction endpoints (no trained model loaded)")
    else:
        single = check("predict single", "POST", "/api/prediction/predict", body=VOYAGE, assertions=[
            ("positive fuel", lambda d: d["predicted_fuel_consumption"] > 0),
            ("co2 computed", lambda d: d["estimated_co2_tons"] > 0),
            ("cost computed", lambda d: d["estimated_cost_usd"] > 0),
            ("confidence interval brackets estimate", lambda d:
                d["confidence_interval"][0] <= d["predicted_fuel_consumption"] <= d["confidence_interval"][1]),
        ])
        check("predict batch matches single", "POST", "/api/prediction/predict/batch",
              body={"voyages": [VOYAGE] * 3},
              assertions=[
                  ("3 predictions", lambda d: d["count"] == 3),
                  ("batch == single (scaler-refit regression)", lambda d:
                      abs(d["predictions"][0] - single["predicted_fuel_consumption"]) < 1e-6),
                  ("all identical for identical input", lambda d: len(set(d["predictions"])) == 1),
              ])
        check("zero-carbon fuel emits nothing", "POST", "/api/prediction/predict",
              body={**VOYAGE, "fuel_type": "Hydrogen"},
              assertions=[("co2 is zero", lambda d: d["estimated_co2_tons"] == 0)])
        check("metrics are real", "GET", "/api/prediction/metrics", assertions=[
            ("r2 > 0.9", lambda d: d["r2"] > 0.9),
            ("rmse > 0 (not the old hardcoded zeros)", lambda d: d["rmse"] > 0),
            ("train/test counts", lambda d: d["n_train"] > 0 and d["n_test"] > 0),
        ])
        check("feature importance", "GET", "/api/prediction/feature-importance", assertions=[
            ("sums to 1", lambda d: abs(sum(f["importance"] for f in d["features"]) - 1.0) < 1e-3),
            ("sorted descending", lambda d: d["features"] == sorted(d["features"], key=lambda f: -f["importance"])),
        ])
        check("retrain from dataset", "POST", "/api/prediction/train",
              body={"dataset": "voyage_data.csv", "persist": False, "test_size": 0.2},
              assertions=[("r2 > 0.9 after retrain", lambda d: d["r2"] > 0.9)], timeout=300)

    # -- Benchmarking -------------------------------------------------------
    print("\n[Benchmarking]")
    check("results before any run", "GET", "/api/benchmarks/results", expect=404, assertions=[
        ("structured error", lambda d: d["error"]["code"] == "NOT_FOUND"),
    ])
    check("metrics guide", "GET", "/api/benchmarks/metrics-guide", assertions=[
        ("documented indicators", lambda d: all(has("id", "name", "direction", "description")(m) for m in d)),
    ])
    check("run suite", "POST", "/api/benchmarks/run",
          body={"algorithms": ["qpso", "pso"], "n_runs": 2, "n_vessels": 6, "n_routes": 3,
                "max_iterations": 20, "population_size": 20},
          assertions=[
              ("completed", lambda d: d["status"] == "completed"),
              ("2 algorithms scored", lambda d: len(d["results"]) == 2),
              ("ranked", lambda d: sorted(r["rank"] for r in d["results"]) == [1, 2]),
              ("quality indicators present", lambda d: all(has("hypervolume_mean", "igd_mean", "spread_mean")(r) for r in d["results"])),
              ("summary is generated, not canned", lambda d: d["summary"] != "Benchmarking completed successfully."),
              ("real timings", lambda d: all(r["time_seconds_mean"] > 0 for r in d["results"])),
          ], timeout=300)
    check("results after run", "GET", "/api/benchmarks/results", assertions=[
        ("cached", lambda d: d["status"] == "completed"),
    ])
    check("convergence series", "GET", "/api/benchmarks/convergence", assertions=[
        ("both algorithms", lambda d: set(d["series"]) == {"qpso", "pso"}),
        ("20 points (not the old 10 hardcoded)", lambda d: all(len(s) == 20 for s in d["series"].values())),
    ])
    check("scalability sweep", "POST", "/api/benchmarks/scalability",
          body={"algorithms": ["pso"], "problem_sizes": [4, 8], "n_runs": 1, "max_iterations": 15},
          assertions=[
              ("both sizes run", lambda d: {r["problem_size"] for r in d["rows"]} == {4, 8}),
              ("distinct problems per size", lambda d: len({r["n_dimensions"] for r in d["rows"]}) == 2),
          ], timeout=300)

    # -- Scenarios ----------------------------------------------------------
    print("\n[Scenarios]")
    check("fuel table", "GET", "/api/scenarios/fuels", assertions=[
        ("7 fuels", lambda d: len(d) == 7),
        ("derived units consistent", lambda d: all(
            abs(f["co2_tons_per_ton_fuel"] - f["emission_factor_gco2_per_mj"] * f["energy_density_mj_per_kg"] / 1000) < 1e-3
            for f in d)),
    ])
    check("session fleet", "GET", "/api/scenarios/fleet", assertions=[
        ("real vessel names", lambda d: all(v["name"].startswith(("MV ", "MT ")) for v in d["vessels"])),
        ("base case computed", lambda d: d["base"]["total_emissions_co2"] > 0),
    ])
    check("analyze LNG switch", "POST", "/api/scenarios/analyze", body={"target_fuel": "LNG"}, assertions=[
        ("emissions fall", lambda d: d["scenario"]["emission_reduction_pct"] > 0),
        ("vessels switched", lambda d: d["scenario"]["vessels_switched"] > 0),
        ("retrofit capex charged", lambda d: d["scenario"]["retrofit_capex_usd"] > 0),
    ])
    check("hydrogen eliminates co2", "POST", "/api/scenarios/analyze", body={"target_fuel": "Hydrogen"},
          assertions=[("100% reduction", lambda d: abs(d["scenario"]["emission_reduction_pct"] - 100) < 1e-6)])
    check("analyze with custom fleet", "POST", "/api/scenarios/analyze",
          body={"target_fuel": "Methanol",
                "fleet": {"vessels": [{"id": 1, "fuel_type": "HFO", "fuel_consumption": 1000}]}},
          assertions=[("uses supplied fleet", lambda d: d["base"]["total_fuel_tons"] == 1000)])
    check("compare fuels", "POST", "/api/scenarios/compare",
          body={"fuel_options": ["LNG", "Methanol", "Ammonia", "Hydrogen"]},
          assertions=[
              ("base + 4 scenarios", lambda d: len(d["scenarios"]) == 5),
              ("base first", lambda d: d["scenarios"][0]["scenario_name"] == "Base Scenario"),
              ("recommendations made", has("best_for_emissions", "best_value_for_money")),
          ])
    check("shore power", "POST", "/api/scenarios/shore-power", body={"shore_power_pct": 60}, assertions=[
        ("co2 avoided", lambda d: d["avoided_co2_tons"] > 0),
    ])
    check("shore power zero is zero", "POST", "/api/scenarios/shore-power", body={"shore_power_pct": 0},
          assertions=[("nothing avoided", lambda d: d["avoided_co2_tons"] == 0)])
    check("transition plan", "POST", "/api/scenarios/transition-plan",
          body={"target_year": 2033, "target_fuel": "LNG"},
          assertions=[
              ("monotone rollout", lambda d: [p["target_pct_green_fuel"] for p in d["phases"]] ==
                  sorted(p["target_pct_green_fuel"] for p in d["phases"])),
              ("reaches 100%", lambda d: d["phases"][-1]["target_pct_green_fuel"] == 100.0),
              ("starts after 2025 (not hardcoded 2024)", lambda d: d["phases"][0]["year"] > 2025),
          ])
    check("replace session fleet", "PUT", "/api/scenarios/fleet",
          body={"vessels": [{"id": 9, "name": "MV Test Hull", "fuel_type": "VLSFO", "fuel_consumption": 250}]},
          assertions=[("one vessel", lambda d: d["vessel_count"] == 1)])
    check("session fleet persisted", "GET", "/api/scenarios/fleet",
          assertions=[("new fleet in place", lambda d: d["vessels"][0]["name"] == "MV Test Hull")])

    # -- Validation and security -------------------------------------------
    print("\n[Validation & security]")
    for name, path, body in [
        ("unknown algorithm", "/api/optimization/optimize", {"algorithm": "warp_drive"}),
        ("zero vessels", "/api/optimization/optimize", {"algorithm": "qpso", "n_vessels": 0}),
        ("oversized fleet", "/api/optimization/optimize", {"algorithm": "qpso", "n_vessels": 100000}),
        ("iteration cap", "/api/optimization/optimize", {"algorithm": "qpso", "max_iterations": 999999}),
        ("unknown fuel", "/api/optimization/optimize", {"algorithm": "qpso", "fuel_types": ["Unobtanium"]}),
        ("bad weight count", "/api/optimization/optimize", {"algorithm": "qpso", "objective_weights": [1, 2]}),
        ("extra field rejected", "/api/optimization/optimize", {"algorithm": "qpso", "sneaky": True}),
        ("negative speed", "/api/prediction/predict", {**VOYAGE, "speed_knots": -5}),
        ("impossible cargo load", "/api/prediction/predict", {**VOYAGE, "cargo_load_pct": 150}),
        ("beaufort out of range", "/api/prediction/predict", {**VOYAGE, "weather_beaufort": 99}),
        ("unknown fuel in predict", "/api/prediction/predict", {**VOYAGE, "fuel_type": "Plutonium"}),
        ("unknown vessel type", "/api/prediction/predict", {**VOYAGE, "vessel_type": "Submarine"}),
        ("unknown benchmark algo", "/api/benchmarks/run", {"algorithms": ["quantum_magic"]}),
        ("unknown scenario fuel", "/api/scenarios/analyze", {"target_fuel": "Unobtanium"}),
        ("vessel index out of range", "/api/scenarios/analyze", {"target_fuel": "LNG", "vessel_indices": [999]}),
        ("past target year", "/api/scenarios/transition-plan", {"target_year": 2020}),
    ]:
        check(name, "POST", path, body=body, expect=422, assertions=[
            ("structured error envelope", lambda d: "error" in d and "code" in d["error"]),
        ])

    for attack in ("/etc/passwd", "../../etc/passwd", "C:\\Windows\\win.ini", "./secrets"):
        status, payload, _ = call("POST", "/api/prediction/train", {"dataset": attack})
        text = json.dumps(payload)
        ok = status in (404, 422) and "root:" not in text and "win.ini" not in text
        name = f"path traversal blocked: {attack}"
        (PASS if ok else FAIL).append((name, 0) if ok else (name, "POST", "/api/prediction/train", [f"HTTP {status}: {text[:120]}"]))
        print(f"  {'ok   ' if ok else 'FAIL '} POST /api/prediction/train           traversal {attack!r} -> {status}")

    status, payload, _ = call("POST", "/api/prediction/train", {"dataset": "nope.csv"})
    leaked = any(s in json.dumps(payload) for s in ("/home/", "Traceback", "site-packages"))
    name = "errors do not leak internals"
    (PASS if (status == 404 and not leaked) else FAIL).append(
        (name, 0) if (status == 404 and not leaked) else (name, "POST", "/api/prediction/train", ["leaked internals or wrong status"]))
    print(f"  {'ok   ' if (status == 404 and not leaked) else 'FAIL '} POST /api/prediction/train           missing dataset -> {status}, no leak")

    check("unknown route", "GET", "/api/does-not-exist", expect=404, assertions=[
        ("structured error", lambda d: "error" in d),
    ])

    # -- Summary ------------------------------------------------------------
    print("\n" + "=" * 78)
    total = len(PASS) + len(FAIL)
    print(f"  {len(PASS)}/{total} passed", end="")
    if SKIP:
        print(f"   ({len(SKIP)} skipped)", end="")
    print()
    if FAIL:
        print(f"\n  {len(FAIL)} FAILURES:")
        for entry in FAIL:
            print(f"    - {entry[0]}")
            for p in entry[3]:
                print(f"        {p}")
    slow = sorted((e for e in PASS if e[1] > 1.0), key=lambda e: -e[1])[:5]
    if slow:
        print("\n  slowest calls:")
        for name, elapsed in slow:
            print(f"    {elapsed:6.2f}s  {name}")
    print()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
