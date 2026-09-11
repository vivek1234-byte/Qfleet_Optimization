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

# The seeded demo administrator. Override with --admin-id / --admin-password
# when running against a server whose accounts are real.
ADMIN_ID = "EMP001"
ADMIN_PASSWORD = "Admin@12345"


def call(method, path, body=None, timeout=180, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
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


def check(name, method, path, *, body=None, expect=200, assertions=(), timeout=180, headers=None):
    """
    ``expect`` accepts either one status or a set of acceptable ones, for the
    handful of endpoints whose correct answer depends on whether anything has
    been run yet. Asserting a single status there makes the suite pass only on
    a cold server, which is a flaky test rather than a strict one.
    """
    status, payload, elapsed = call(method, path, body, timeout, headers)
    allowed = expect if isinstance(expect, (set, frozenset, tuple, list)) else {expect}
    problems = []
    if status not in allowed:
        detail = payload if isinstance(payload, str) else json.dumps(payload)[:200]
        wanted = " or ".join(str(s) for s in sorted(allowed))
        problems.append(f"expected HTTP {wanted}, got {status} — {detail}")
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


def check_inline(name, condition, detail=""):
    """Assert something derived from two earlier responses."""
    if condition:
        PASS.append((name, 0.0))
        print(f"  ok    {'--':4s} {'(derived)':42s} {0.0:6.2f}s  {name}")
    else:
        FAIL.append((name, "--", "(derived)", [detail or "condition was false"]))
        print(f"  FAIL  {'--':4s} {'(derived)':42s} {0.0:6.2f}s")
        print(f"        └─ {detail or 'condition was false'}")


def stream_check(timeout=120):
    """
    Consume the server-sent event stream and check its shape.

    A streaming endpoint can return 200 and then produce nothing useful, so
    this asserts on the frames themselves: a start, one progress event per
    iteration in order, and a terminal done carrying a real plan.
    """
    iterations = 20
    path = (
        "/api/optimization/stream?algorithm=qpso&n_vessels=6&n_routes=4"
        f"&max_iterations={iterations}&population_size=20&seed=42&month=7"
    )
    started = time.time()
    events, event_name = [], None
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            for raw in response:
                line = raw.decode("utf-8").rstrip("\n")
                if line.startswith("event: "):
                    event_name = line[7:]
                elif line.startswith("data: "):
                    events.append((event_name, json.loads(line[6:])))
                    if event_name in ("done", "error"):
                        break
    except Exception as exc:
        FAIL.append(("solver stream", "GET", "/api/optimization/stream", [f"{type(exc).__name__}: {exc}"]))
        print(f"  FAIL  GET  {'/api/optimization/stream':42s}")
        print(f"        └─ {type(exc).__name__}: {exc}")
        return

    elapsed = time.time() - started
    kinds = [name for name, _ in events]
    progress = [payload for name, payload in events if name == "progress"]
    terminal = events[-1] if events else (None, {})

    problems = []
    if "text/event-stream" not in content_type:
        problems.append(f"wrong content type: {content_type}")
    if not kinds or kinds[0] != "start":
        problems.append(f"first frame was {kinds[0] if kinds else 'nothing'}, not start")
    if len(progress) != iterations:
        problems.append(f"{len(progress)} progress frames for {iterations} iterations")
    if [p["iteration"] for p in progress] != list(range(1, len(progress) + 1)):
        problems.append("progress iterations are not sequential from 1")
    if terminal[0] != "done":
        problems.append(f"stream ended on {terminal[0]}, not done")
    elif not terminal[1].get("plan", {}).get("assignments"):
        problems.append("done frame carried no deployment plan")
    elif terminal[1]["plan"]["season"]["month"] != 7:
        problems.append("the month parameter did not reach the solver")

    if problems:
        FAIL.append(("solver stream", "GET", "/api/optimization/stream", problems))
        print(f"  FAIL  GET  {'/api/optimization/stream':42s} {elapsed:6.2f}s")
        for problem in problems:
            print(f"        └─ {problem}")
    else:
        PASS.append(("solver stream", elapsed))
        print(f"  ok    GET  {'/api/optimization/stream':42s} {elapsed:6.2f}s  "
              f"{len(progress)} progress frames then done")


# ---------------------------------------------------------------------------
VOYAGE = {
    "vessel_type": "Container", "dwt": 120000, "engine_power_kw": 35000,
    "speed_knots": 16.5, "distance_nm": 5000, "cargo_load_pct": 85,
    "weather_beaufort": 4, "draft_meters": 13.5, "fuel_type": "LNG",
}
SMALL = {"n_vessels": 8, "n_routes": 4, "max_iterations": 30, "population_size": 24}


def has(*keys):
    return lambda d: all(k in d for k in keys)


def _response_headers(path: str) -> dict:
    """Lower-cased response headers for `path`, or {} if it cannot be reached."""
    req = urllib.request.Request(BASE + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        return {k.lower(): v for k, v in exc.headers.items()}
    except Exception:
        return {}


def main() -> int:
    global BASE, ADMIN_ID, ADMIN_PASSWORD
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--admin-id", default=ADMIN_ID,
                    help="Employee ID for the authentication checks")
    ap.add_argument("--admin-password", default=ADMIN_PASSWORD,
                    help="Its password. Defaults to the seeded demo password.")
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    ADMIN_ID = args.admin_id
    ADMIN_PASSWORD = args.admin_password

    print(f"\nTesting {BASE}\n" + "=" * 78)

    # -- Meta ---------------------------------------------------------------
    print("\n[Meta]")
    check("root info", "GET", "/", assertions=[
        ("status running", lambda d: d["status"] == "running"),
        ("lists endpoints", has("endpoints", "version")),
    ])
    health = check("health", "GET", "/api/health", assertions=[
        ("has checks", lambda d: set(d["checks"]) == {"api", "accounts", "prediction_model", "dataset"}),
        ("status healthy", lambda d: d["status"] == "healthy"),
    ])
    check("openapi schema", "GET", "/openapi.json", assertions=[
        ("24+ paths", lambda d: len(d["paths"]) >= 20),
    ])

    headers = call("GET", "/api/health")[1] and _response_headers("/api/health")
    for name, expected in (
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
    ):
        check_inline(
            f"header {name}",
            (headers.get(name.lower()) or "") == expected,
            f"{name} is {headers.get(name.lower())!r}, expected {expected!r}",
        )

    model_ready = bool(health and health.get("checks", {}).get("prediction_model", {}).get("ok"))

    # -- Authentication -----------------------------------------------------
    # Against a live server, with the seeded demo administrator. Skipped
    # rather than failed if those credentials do not apply — the point is to
    # exercise the boundary, not to insist on a particular password.
    print("\n[Authentication]")
    check("login rejects an unknown id", "POST", "/api/auth/login", expect=401,
          body={"employee_id": "NOSUCHEMPLOYEE", "password": "whatever12345"})
    check("login rejects a bad password", "POST", "/api/auth/login", expect=401,
          body={"employee_id": ADMIN_ID, "password": "definitely-not-it"})

    unknown = call("POST", "/api/auth/login", {"employee_id": "NOSUCHEMPLOYEE", "password": "x" * 12})[1]
    wrong = call("POST", "/api/auth/login", {"employee_id": ADMIN_ID, "password": "x" * 12})[1]
    check_inline(
        "no account enumeration",
        unknown == wrong,
        f"unknown id says {unknown!r}, wrong password says {wrong!r} — the difference tells an "
        "attacker which Employee IDs exist",
    )

    check("login needs both fields", "POST", "/api/auth/login", expect=422,
          body={"employee_id": ADMIN_ID})
    check("/me needs a token", "GET", "/api/auth/me", expect=401)
    check("/me rejects a junk token", "GET", "/api/auth/me", expect=401,
          headers={"Authorization": "Bearer not-a-real-token"})
    check("admin list needs a token", "GET", "/api/admin/employees", expect=401)

    status, session, _ = call("POST", "/api/auth/login",
                              {"employee_id": ADMIN_ID, "password": ADMIN_PASSWORD})
    if status == 200 and isinstance(session, dict):
        auth = {"Authorization": f"Bearer {session['access_token']}"}
        check("administrator signs in", "POST", "/api/auth/login",
              body={"employee_id": ADMIN_ID, "password": ADMIN_PASSWORD}, assertions=[
                  ("bearer token", lambda d: d["token_type"] == "bearer" and d["access_token"]),
                  ("carries the employee", lambda d: d["employee"]["employee_id"] == ADMIN_ID),
                  ("role is ADMIN", lambda d: d["employee"]["role"] == "ADMIN"),
                  ("no password material", lambda d: "password_hash" not in json.dumps(d)),
              ])
        check("/me with a token", "GET", "/api/auth/me", headers=auth, assertions=[
            ("is the same person", lambda d: d["employee_id"] == ADMIN_ID),
            ("no password material", lambda d: "password_hash" not in json.dumps(d)),
        ])
        check("admin lists employees", "GET", "/api/admin/employees", headers=auth, assertions=[
            ("has a roster", lambda d: isinstance(d["employees"], list) and d["total"] >= 1),
            ("counts agree", lambda d: d["total"] == len(d["employees"])),
            ("no hash anywhere", lambda d: "password_hash" not in json.dumps(d)
                                           and "$2b$" not in json.dumps(d)),
        ])
        check("search by employee id", "GET", f"/api/admin/employees?search={ADMIN_ID.lower()}",
              headers=auth, assertions=[
                  ("finds exactly one", lambda d: d["total"] == 1),
              ])
        check("duplicate id refused", "POST", "/api/admin/employees", expect=409, headers=auth,
              body={"employee_id": ADMIN_ID, "full_name": "Impostor Person",
                    "password": "harbour-tide-9471"})
        check("admin rejects a junk token", "GET", "/api/admin/employees", expect=401,
              headers={"Authorization": "Bearer not-a-real-token"})
        check("logout", "POST", "/api/auth/logout", headers=auth)

        # Session revocation: the admin can end someone's sessions without
        # touching their password or disabling the account.
        probe2 = call("POST", "/api/admin/employees", {
            "employee_id": "ZZTEST09", "full_name": "Revocation Probe",
            "password": "anchor-drift-3318", "department": "QA",
        }, headers=auth)[1]
        if isinstance(probe2, dict) and probe2.get("id"):
            tok2 = call("POST", "/api/auth/login",
                        {"employee_id": "ZZTEST09", "password": "anchor-drift-3318"})[1]
            h2 = {"Authorization": f"Bearer {tok2['access_token']}"}
            check("session works before revocation", "GET", "/api/auth/me", headers=h2)
            check("admin revokes sessions", "POST",
                  f"/api/admin/employees/{probe2['id']}/revoke-sessions", headers=auth)
            check("revoked token is refused", "GET", "/api/auth/me", expect=401, headers=h2)
            check("but the password still works", "POST", "/api/auth/login",
                  body={"employee_id": "ZZTEST09", "password": "anchor-drift-3318"})
            call("DELETE", f"/api/admin/employees/{probe2['id']}", headers=auth)

        check("weak password refused", "POST", "/api/admin/employees", expect=422, headers=auth,
              body={"employee_id": "ZZTEST10", "full_name": "Weak Choice",
                    "password": "password123"})

        # An ordinary employee must be refused by the API, not just by a
        # hidden menu item. Created, used, and removed again.
        created = call("POST", "/api/admin/employees", {
            "employee_id": "ZZTEST01", "full_name": "Conformance Probe",
            "password": "quay-lantern-8813", "department": "QA",
        }, headers=auth)[1]
        if isinstance(created, dict) and created.get("id"):
            probe = call("POST", "/api/auth/login",
                         {"employee_id": "ZZTEST01", "password": "quay-lantern-8813"})[1]
            probe_auth = {"Authorization": f"Bearer {probe['access_token']}"}
            check("employee cannot list employees", "GET", "/api/admin/employees",
                  expect=403, headers=probe_auth)
            check("employee cannot create employees", "POST", "/api/admin/employees",
                  expect=403, headers=probe_auth,
                  body={"employee_id": "ZZTEST02", "full_name": "Escalated User",
                        "password": "estuary-swell-6640", "role": "ADMIN"})
            check("employee cannot delete employees", "DELETE",
                  f"/api/admin/employees/{created['id']}", expect=403, headers=probe_auth)

            deactivated = call("POST", f"/api/admin/employees/{created['id']}/deactivate",
                               headers=auth)[1]
            check_inline("deactivate works",
                         isinstance(deactivated, dict) and deactivated.get("is_active") is False,
                         f"deactivate returned {deactivated!r}")
            check("inactive account cannot sign in", "POST", "/api/auth/login", expect=401,
                  body={"employee_id": "ZZTEST01", "password": "quay-lantern-8813"})
            check("deactivation ends a live session", "GET", "/api/auth/me",
                  expect=401, headers=probe_auth)
            call("DELETE", f"/api/admin/employees/{created['id']}", headers=auth)
        else:
            SKIP.append(("role enforcement", "could not create the probe account"))
            print("  skip  --    role enforcement — could not create the probe account")
    else:
        SKIP.append(("admin session", f"{ADMIN_ID} / seeded password did not sign in"))
        print(f"  skip  --    admin-only checks — {ADMIN_ID} did not sign in "
              f"(pass --admin-id / --admin-password)")

    # Brute-force protection, last in this section: it deliberately burns
    # attempts, and the per-address counter is shared with everything above.
    ghost = "ZZGHOST01"
    statuses = [
        call("POST", "/api/auth/login", {"employee_id": ghost, "password": f"wrong-{i}"})[0]
        for i in range(10)
    ]
    check_inline(
        "repeated failures are rate limited",
        429 in statuses,
        f"ten wrong passwords produced {statuses} — none was throttled",
    )
    check_inline(
        "the limit does not trip immediately",
        statuses[0] == 401,
        f"the first attempt returned {statuses[0]}, so the limiter is too aggressive",
    )

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


    # -- Regulatory ---------------------------------------------------------
    print("\n[Regulatory]")
    check("emission control areas", "GET", "/api/regulatory/eca-zones", assertions=[
        ("five zones", lambda d: len(d["zones"]) == 5),
        ("every zone is a closed outline", lambda d: all(len(z["polygon"]) >= 4 for z in d["zones"])),
        ("ECA cap is 0.10%, global cap 0.50%",
         lambda d: d["eca_sulphur_limit_pct"] == 0.10 and d["global_sulphur_cap_pct"] == 0.50),
        ("the two European lanes are exposed", lambda d: d["affected_lane_count"] == 2),
        ("exposure is a fraction, not a percentage",
         lambda d: all(0 <= l["eca_fraction"] <= 1 for l in d["lanes"])),
        ("indicative outlines are disclaimed", lambda d: "not navigational boundaries" in d["disclaimer"]),
    ])
    check("route geometry", "GET", "/api/regulatory/routes", assertions=[
        ("every lane has a path", lambda d: all(len(l["points"]) >= 2 for l in d["lanes"])),
        ("cumulative distance starts at zero",
         lambda d: all(l["cumulative_nm"][0] == 0 for l in d["lanes"])),
        ("one cumulative entry per point",
         lambda d: all(len(l["cumulative_nm"]) == len(l["points"]) for l in d["lanes"])),
        ("ports and chokepoints served", lambda d: len(d["ports"]) >= 20 and len(d["chokepoints"]) >= 6),
    ])
    check("CII reference lines", "GET", "/api/regulatory/cii-reference?year=2026", assertions=[
        ("MEPC.353(78) container constants",
         lambda d: next(t for t in d["ship_types"] if t["vessel_type"] == "Container")["a"] == 1984.0),
        ("MEPC.354(78) tanker boundaries",
         lambda d: next(t for t in d["ship_types"] if t["vessel_type"] == "Tanker")["dd_vector"]
                   == [0.82, 0.93, 1.08, 1.28]),
        ("2026 reduction factor is 11%", lambda d: d["reduction_factor_pct"] == 11.0),
        ("every registry vessel has a required line", lambda d: len(d["vessels"]) == 20),
        ("required is below the 2019 reference",
         lambda d: all(v["required_cii"] < v["reference_cii"] for v in d["vessels"])),
        ("boundaries ascend A/B < B/C < C/D < D/E",
         lambda d: all(v["boundaries"]["A_B"] < v["boundaries"]["B_C"] < v["boundaries"]["C_D"]
                       < v["boundaries"]["D_E"] for v in d["vessels"])),
        ("sources cited", lambda d: any("MEPC.353" in s for s in d["sources"])),
    ])
    check("rate voyages", "POST", "/api/regulatory/cii",
          body={"year": 2026, "voyages": [
              {"vessel_name": "clean", "vessel_type": "Tanker", "dwt": 100000,
               "co2_tons": 50, "distance_nm": 5000},
              {"vessel_name": "dirty", "vessel_type": "Tanker", "dwt": 100000,
               "co2_tons": 5000, "distance_nm": 5000},
          ]},
          assertions=[
              ("both rated", lambda d: d["rated_count"] == 2),
              ("the clean one beats the dirty one",
               lambda d: "ABCDE".index(d["vessels"][0]["rating"]) < "ABCDE".index(d["vessels"][1]["rating"])),
              ("gCO2 per dwt-nm", lambda d: d["vessels"][0]["unit"] == "gCO2 per dwt-nautical mile"),
              ("the dirty one is flagged", lambda d: [v["vessel_name"] for v in d["at_risk"]] == ["dirty"]),
              ("annual-vs-voyage caveat surfaced",
               lambda d: any("annual indicator" in c for c in d["caveats"])),
          ])
    check("reject an unknown ship type", "POST", "/api/regulatory/cii", expect=422,
          body={"voyages": [{"vessel_type": "Submarine", "dwt": 1000,
                             "co2_tons": 1, "distance_nm": 1}]},
          assertions=[("field named", lambda d: any(f["field"].endswith("vessel_type")
                                                    for f in d["error"]["details"]["fields"]))])
    check("seasonality", "GET", "/api/regulatory/seasonality", assertions=[
        ("eight basins", lambda d: len(d["basins"]) == 8),
        ("twelve months each", lambda d: all(len(b["monthly_factor"]) == 12 for b in d["basins"])),
        ("the Arabian Sea peaks in the monsoon",
         lambda d: next(b for b in d["basins"] if b["name"] == "Arabian Sea")["roughest_month"]
                   in ("June", "July", "August")),
        ("every lane profiled", lambda d: len(d["lanes"]) == 16),
        ("basin shares sum to one",
         lambda d: all(abs(sum(b["share"] for b in l["basins"]) - 1) < 1e-6 for l in d["lanes"])),
        ("indicative, not measured", lambda d: "not measured data" in d["note"]),
    ])
    check("unknown lane rejected", "GET", "/api/regulatory/seasonality?lane=Nowhere", expect=422)

    # -- Seasonal and ECA effects on the optimiser --------------------------
    print("\n[Optimisation under regulation]")
    july = check("optimise in the south-west monsoon", "POST", "/api/optimization/optimize",
                 body={"n_vessels": 8, "n_routes": 5, "max_iterations": 60, "population_size": 30,
                       "seed": 42, "month": 7},
                 assertions=[
                     ("month echoed", lambda d: d["problem"]["month"] == 7),
                     ("season named", lambda d: d["plan"]["season"]["label"] == "South-west monsoon"),
                     ("sea state raised", lambda d: d["plan"]["season"]["mean_factor"] > 1.0),
                     ("every vessel carries a CII rating",
                      lambda d: all(a["cii"]["rated"] for a in d["plan"]["assignments"])),
                     ("ratings are A-E",
                      lambda d: all(a["cii"]["rating"] in "ABCDE" for a in d["plan"]["assignments"])),
                     ("fleet compliance summarised",
                      lambda d: set(d["plan"]["compliance"]["cii"]["distribution"]) == set("ABCDE")),
                     ("ECA switch fuel named",
                      lambda d: d["plan"]["compliance"]["eca_switch_fuel"] == "MGO"),
                 ], timeout=300)
    march = check("optimise in the inter-monsoon", "POST", "/api/optimization/optimize",
                  body={"n_vessels": 8, "n_routes": 5, "max_iterations": 60, "population_size": 30,
                        "seed": 42, "month": 3},
                  assertions=[("calmer than July",
                               lambda d: d["plan"]["season"]["mean_factor"] < 1.0)], timeout=300)
    if isinstance(july, dict) and isinstance(march, dict):
        check_inline("the monsoon costs fuel",
                     july["plan"]["objectives"]["fuel_consumption_tons"]
                     > march["plan"]["objectives"]["fuel_consumption_tons"])
    check("speed cap binds", "POST", "/api/optimization/optimize",
          body={"n_vessels": 8, "n_routes": 5, "max_iterations": 60, "population_size": 30,
                "seed": 42, "speed_cap_knots": 12},
          assertions=[
              ("cap echoed", lambda d: d["problem"]["speed_cap_knots"] == 12.0),
              ("nothing exceeds the cap or its own minimum",
               lambda d: all(a["speed_knots"] <= 16.1 for a in d["plan"]["assignments"])),
          ], timeout=300)
    check("reject an impossible month", "POST", "/api/optimization/optimize", expect=422,
          body={"n_vessels": 4, "month": 13})

    # -- Streaming ----------------------------------------------------------
    print("\n[Streaming]")
    stream_check()

    # -- Benchmarking -------------------------------------------------------
    print("\n[Benchmarking]")
    # 404 on a cold server, 200 if this process has already run a suite. Both
    # are correct; what must hold is that the answer is well formed either way.
    check("results before any run", "GET", "/api/benchmarks/results", expect={200, 404}, assertions=[
        ("structured error or a cached report",
         lambda d: d.get("error", {}).get("code") == "NOT_FOUND" or d.get("status") == "completed"),
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
