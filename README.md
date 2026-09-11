# 🚢 Quantum Green Fleet

Quantum-inspired multi-objective optimisation for maritime fleet decarbonisation.

![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Tests](https://img.shields.io/badge/tests-129%20passing-brightgreen.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## Problem

Shipping moves ~80% of world trade and emits roughly 3% of global CO₂. Cutting
that means solving three objectives at once — **fuel burn**, **greenhouse-gas
emissions** and **operating cost** — which pull against each other. Slow steaming
saves fuel but blows schedules; LNG cuts CO₂ but costs more per gigajoule and
needs a retrofit; ammonia is zero-carbon at the stack but barely bunkerable
today.

This platform searches that trade-off space with quantum-inspired metaheuristics
and reports a real Pareto front, not a single compromised answer.

## What it does

| Module | What it gives you |
| --- | --- |
| **Fuel prediction** | Gradient-boosted model estimating voyage fuel burn from vessel spec, route and weather (R² ≈ 0.99, ~4% mean absolute error) |
| **Fleet optimizer** | Assigns vessels to routes and picks speed, fuel and shore-power level to minimise fuel, CO₂e and cost simultaneously |
| **Benchmarking** | Runs QPSO, QGA, PSO and NSGA-II head to head with hypervolume, IGD, IGD+, spread and spacing |
| **Scenario analysis** | Compares alternative fuels on emissions, cost, retrofit capex, marginal abatement cost and practical readiness |

### Algorithms

| ID | Algorithm | Type | Objectives |
| --- | --- | --- | --- |
| `qpso` | Quantum Particle Swarm Optimization | Quantum-inspired swarm | Multi-objective, external Pareto archive |
| `qga` | Quantum Genetic Algorithm | Quantum-inspired evolutionary | Scalarised |
| `pso` | Particle Swarm Optimization | Classical swarm | Scalarised |
| `nsga2` | NSGA-II | Classical evolutionary | Multi-objective |

The optimisation model is a real one: cubic speed–power law, fuel-specific
consumption, seasonal weather by sea basin, cargo-load correction, port hotel
load offset by shore power, a priced fuel switch inside MARPOL Annex VI
emission control areas, and constraints for route demand coverage, schedule
windows, bunker tank range and fuel availability. Every plan comes back with an
IMO carbon intensity rating per vessel. Every solver is warm-started from a feasible
baseline plan, so a run can never report a result worse than doing nothing.

## Tech stack

- **Backend** — Python 3.9+, FastAPI, Uvicorn, Pydantic v2
- **Optimisation** — NumPy (fully vectorised), pymoo for quality indicators
- **ML** — scikit-learn, XGBoost, optional PyTorch
- **Frontend** — React 19, Vite, Tailwind, Recharts, and a hand-built inline-SVG
  chart of the world for the voyage simulator (no map library, no tile server)

## The web interface

`frontend/` is a nine-page application covering every endpoint the API exposes,
behind a sign-in screen. There is no auth backend, so any well-formed email and
any password will get you in, and the login screen says as much rather than
implying security it does not have; see `frontend/README.md`.

Three screens carry the argument:

- **Live Simulator** — the fleet sails the real Indian trade-lane network,
  through Suez, Bab-el-Mandeb, Hormuz and Malacca, in accelerated time, with
  fuel burnt, CO2 emitted and voyage cost ticking up live. Its **split mode**
  puts the unoptimised fleet and the solver's plan on two maps sharing one
  clock, with the gap between them counting up as they sail.
- **What-if Sandbox** — move carbon price, a speed cap or the season and the
  solver re-runs, streaming its convergence curve live over server-sent events.
  Every run is diffed against the last, so you can see exactly which vessels
  changed lane, fuel or speed.
- **Compliance** — an IMO carbon intensity rating for every vessel in the plan,
  the emission control areas drawn on the map, and the published constants so a
  reviewer can check the arithmetic instead of trusting it.

Everything it needs is bundled: coastlines, fonts, styles. It makes no network
call except to this API, which matters when the venue Wi-Fi does not work. See
`frontend/README.md` for the details.

## Quick start

```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Generate the dataset and train the prediction model (first run only):

```bash
cd ..
python train_model.py --generate 10000
```

Set up the accounts database (first run only):

```bash
cd ..
cp .env.example .env              # Windows: copy .env.example .env
# put a real signing key in .env:
python -c "import secrets; print(secrets.token_urlsafe(48))"

python -m alembic upgrade head    # creates backend/data/qfleet.db
python -m backend.manage seed     # demo staff, or `bootstrap` for one admin
```

Start the API:

```bash
cd backend
uvicorn main:app --reload --host 127.0.0.1
```

Start the web interface (needs Node 18+), in a second terminal:

```bash
cd frontend
npm install          # first run only
npm run dev
```

- **Web UI: <http://localhost:5173>**
- API: <http://localhost:8000>
- Interactive docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/api/health>

Or simply run `start.bat` (Windows) / `./start.sh` — it does all of the above
and opens both servers. `./start.sh --api-only` skips the UI.

Both servers bind to `127.0.0.1`, so nothing on the local network can reach
them. That is deliberate; change it only for a considered deployment.

## Signing in

> Full setup, operation and the reasoning behind it: **[ACCOUNTS.md](ACCOUNTS.md)**.

The platform is behind an **Employee ID and password**, checked against an
`employees` table. Passwords are stored as bcrypt hashes and nothing — not the
API, not the admin dashboard — can read one back; the only recovery is a reset.
A successful sign-in returns a signed token that the browser sends as
`Authorization: Bearer …`, and that expires after 12 hours.

`python -m backend.manage seed` creates demo staff:

| Employee ID | Role | Password |
| --- | --- | --- |
| `EMP001` | Administrator | `Admin@12345` |
| `EMP002`–`EMP004` | Employee | `Fleet@12345` |
| `EMP005` | Administrator | `Admin@12345` |

These are demo credentials in a public repository. For anything real, use
`python -m backend.manage bootstrap` instead — it prompts for a password and
creates a single administrator — and change or delete the seeded accounts.

Administrators get an **Employees** page at `/admin` (not linked from the
sidebar — go there by URL): add staff, search,
edit, reset a password, deactivate, delete. Everything on it goes through
`/api/admin/*`, which is behind an administrator check **on the server** —
hiding the sidebar link is presentation, not a permission.

Managing accounts from the command line, for the first admin or a lost
password:

```bash
python -m backend.manage bootstrap                      # the first administrator
python -m backend.manage add EMP010 "Anita Rao" --department Bunkering
python -m backend.manage passwd EMP010                  # prompts, never echoes
python -m backend.manage deactivate EMP010              # revoke without deleting
python -m backend.manage list --search bunkering
```

### What is and is not protected

`/api/auth/*` and `/api/admin/*` require a token; `/api/admin/*` additionally
requires the `ADMIN` role. The optimisation, prediction, benchmarking,
scenario and regulatory routes are **open**, exactly as they were before
accounts existed. That is a deliberate scope line, not an oversight: the
solver stream is consumed with `EventSource`, which cannot send an
`Authorization` header, so locking those routes means moving the token into a
cookie or a query string and reworking the streaming client. They expose
computation over bundled public data and no personal information. To close
them, add `dependencies=[Depends(get_current_employee)]` to each router in
`backend/main.py` and give the stream a cookie-based session.

## API

All errors share one envelope:

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "…", "details": { … } } }
```

### Meta
| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | API information |
| `GET` | `/api/health` | Health and per-subsystem readiness |

### Authentication
| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/auth/login` | Employee ID + password → bearer token |
| `GET` | `/api/auth/me` | The signed-in employee |
| `POST` | `/api/auth/logout` | Sign out on this device |
| `POST` | `/api/auth/logout-everywhere` | End every session for this account |
| `POST` | `/api/auth/change-password` | Change your own password |

### Administration — `ADMIN` only
| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/admin/employees` | List and search (`search`, `role`, `active`) |
| `GET` | `/api/admin/employees/{id}` | One employee |
| `POST` | `/api/admin/employees` | Add an employee |
| `PUT` | `/api/admin/employees/{id}` | Edit name, department, role, email, status |
| `POST` | `/api/admin/employees/{id}/activate` | Reinstate an account |
| `POST` | `/api/admin/employees/{id}/deactivate` | Revoke without deleting |
| `POST` | `/api/admin/employees/{id}/reset-password` | Set a new password (also ends their sessions) |
| `POST` | `/api/admin/employees/{id}/revoke-sessions` | Sign them out everywhere, password unchanged |
| `DELETE` | `/api/admin/employees/{id}` | Delete an employee |

No response from any of these contains `password_hash`.

### Optimization
| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/optimization/algorithms` | Available solvers and their capabilities |
| `GET` | `/api/optimization/fleet` | Inspect the generated fleet, routes and baseline plan |
| `POST` | `/api/optimization/optimize` | Run one solver; returns the Pareto front, convergence trace and deployment plan |
| `POST` | `/api/optimization/compare` | Run several solvers on the *same* problem instance and rank them |

### Prediction
| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/prediction/predict` | Predict one voyage |
| `POST` | `/api/prediction/predict/batch` | Predict many voyages |
| `POST` | `/api/prediction/train` | Retrain on a server-side dataset |
| `GET` | `/api/prediction/metrics` | Metrics from the run that produced the loaded model |
| `GET` | `/api/prediction/feature-importance` | Normalised feature importances |
| `GET` | `/api/prediction/model-info` | Model state, features, valid enum values |

### Benchmarking
| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/benchmarks/run` | Run the suite; returns scored, ranked results |
| `GET` | `/api/benchmarks/results` | Most recent run |
| `GET` | `/api/benchmarks/convergence` | Median convergence trace per algorithm |
| `POST` | `/api/benchmarks/scalability` | Run time and quality as fleet size grows |
| `GET` | `/api/benchmarks/metrics-guide` | What each quality indicator means |

### Regulatory
| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/regulatory/eca-zones` | MARPOL Annex VI areas and per-lane exposure |
| GET | `/api/regulatory/routes` | Port positions, chokepoints, lane waypoint geometry |
| GET | `/api/regulatory/cii-reference` | MEPC reference lines and rating boundaries |
| POST | `/api/regulatory/cii` | Rate a set of voyages A–E |
| GET | `/api/regulatory/seasonality` | Monthly sea-state multipliers by basin and lane |

### Scenarios
| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/scenarios/fuels` | Fuel reference table (shared with the optimizer) |
| `GET` `PUT` | `/api/scenarios/fleet` | Read or replace the session fleet |
| `POST` | `/api/scenarios/analyze` | Switch some or all vessels to a target fuel |
| `POST` | `/api/scenarios/compare` | Base case vs several fuels |
| `POST` | `/api/scenarios/shore-power` | Cold-ironing impact |
| `POST` | `/api/scenarios/transition-plan` | Year-by-year conversion roadmap |

### Example

```bash
curl -X POST http://localhost:8000/api/optimization/optimize \
  -H 'Content-Type: application/json' \
  -d '{"algorithm":"qpso","n_vessels":15,"n_routes":5,"max_iterations":100}'
```

## Configuration

Every setting is an environment variable, read in `backend/config.py`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `QGF_DEBUG` | `false` | Verbose errors and auto-reload |
| `QGF_LOG_LEVEL` | `INFO` | Log level |
| `QGF_CORS_ORIGINS` | localhost dev ports | Comma-separated allowed origins |
| `QGF_MAX_VESSELS` | `60` | Guard rail on request size |
| `QGF_MAX_ITERATIONS` | `400` | Guard rail on solver iterations |
| `QGF_MAX_POPULATION` | `200` | Guard rail on population size |
| `QGF_DATABASE_URL` | `sqlite:///backend/data/qfleet.db` | Accounts database; any SQLAlchemy URL |
| `QGF_JWT_SECRET` | *(random per process)* | Token signing key. **Set this** — without it, every restart signs everyone out |
| `QGF_JWT_ALGORITHM` | `HS256` | Token algorithm |
| `QGF_JWT_EXPIRE_MINUTES` | `720` | Session length |
| `QGF_BCRYPT_ROUNDS` | `12` | Password hashing cost |
| `QGF_PASSWORD_MIN_LENGTH` | `8` | Minimum password length |
| `QGF_LOGIN_MAX_ATTEMPTS_PER_ID` | `8` | Failed sign-ins per Employee ID before a lockout |
| `QGF_LOGIN_MAX_ATTEMPTS_PER_IP` | `30` | Failed sign-ins per client address |
| `QGF_LOGIN_WINDOW_SECONDS` | `300` | Sliding window for both counters |
| `QGF_DISCLOSE_INACTIVE` | `false` | Whether a disabled account is told it is disabled |
| `QGF_HSTS_ENABLED` | `false` | Send HSTS. Turn on only when serving HTTPS |

Values are read from the environment, and from a `.env` file in the project
root if one exists (the environment wins). `.env` is git-ignored;
`.env.example` documents every key with placeholders. **No database
credential or signing key is ever compiled into the frontend** — the browser
only ever sees a bearer token it was handed at sign-in.

### Why SQLite by default

The brief suggested PostgreSQL. The default here is SQLite, for one reason:
this has to start from `start.bat` on a laptop, at a venue, possibly with no
network — and a demo that first needs a database server installed and running
is a demo that fails in the room. SQLAlchemy means Postgres is one variable
away and no code change:

```bash
pip install "psycopg[binary]"
QGF_DATABASE_URL=postgresql+psycopg://qfleet:secret@localhost:5432/qfleet
python -m alembic upgrade head
```

The schema, the migrations and every query are dialect-neutral, and the test
suite runs against either.


## Tests

```bash
cd backend
python -m pytest tests -q
```

298 tests covering the fleet model, all four solvers, the prediction pipeline,
the fuel database, the quality indicators, the regulatory layer and every API
route — including regression tests pinning the specific bugs this version
fixed, and tests that pin the published MEPC constants so a typo in a CII
reference line is a failure rather than a slightly different rating.

`tests/test_auth.py` is the set worth reading: it asserts that no password
is stored or returned in plain text, that a failed sign-in cannot be used to
discover which Employee IDs exist, that every admin route refuses a
non-administrator at the API rather than in the UI, and that deactivating an
account ends a session already in progress.

`apitest.py` is a separate 104-check conformance run against a live server,
including the authentication and role-enforcement boundary:

```bash
python apitest.py --base http://127.0.0.1:8000
```

## Project structure

```
quantum-green-fleet/
├── backend/
│   ├── config.py                    # settings and guard rails
│   ├── main.py                      # FastAPI app, middleware, error handlers
│   ├── core/errors.py               # typed application errors
│   ├── manage.py                    # account administration from the CLI
│   ├── db/
│   │   ├── base.py                  # declarative base and naming convention
│   │   ├── models.py                # Employee
│   │   └── session.py               # engine, session, FastAPI dependency
│   ├── auth/
│   │   ├── security.py              # bcrypt hashing, JWT issue and verify
│   │   ├── schemas.py               # request/response shapes (no password_hash)
│   │   ├── service.py               # the account rules, in one place
│   │   ├── deps.py                  # get_current_employee, require_admin
│   │   └── api.py                   # /api/auth
│   ├── admin/
│   │   └── api.py                   # /api/admin — ADMIN only
│   ├── data/
│   │   ├── fuel_database.py         # single source of truth for fuel properties
│   │   ├── fleet_registry.py        # 20 vessels, 16 trade lanes
│   │   ├── sea_routes.py            # waypoint geometry and ECA polygons
│   │   ├── carbon_intensity.py      # IMO CII reference lines and ratings
│   │   ├── seasonality.py           # monsoon and seasonal weather by basin
│   │   ├── generator.py             # synthetic voyage dataset
│   │   └── datasets/
│   ├── optimization/
│   │   ├── fleet_problem.py         # the physics, costs and constraints
│   │   ├── base.py                  # shared solver machinery, Pareto utilities
│   │   ├── qpso.py  qga.py  pso.py  nsga2.py
│   │   ├── engine.py                # solver registry and result summarisation
│   │   └── api.py
│   ├── prediction/
│   │   ├── models.py                # FuelPredictor
│   │   ├── quantum_feature_sel.py   # QPSO feature selection / hyperparameter tuning
│   │   └── api.py
│   ├── benchmarking/
│   │   ├── metrics.py  runner.py  api.py
│   ├── regulatory/
│   │   └── api.py                   # CII, emission control areas, seasonality
│   ├── scenario/
│   │   ├── analyzer.py  api.py
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/              # AppShell, ui primitives, charts,
│   │   │                            #   WorldMap, ShipLayer (the simulator)
│   │   ├── data/
│   │   │   ├── land.js              # Natural Earth coastlines, baked in
│   │   │   └── geography.js         # ports, lane waypoints, projection
│   │   ├── hooks/                   # useApi, useTheme
│   │   ├── lib/                     # api.js, auth.js, domain.js, nav.js, …
│   │   └── pages/                   # one file per route, incl. Login, Admin
│   ├── vite.config.js               # proxies /api to the backend
│   └── README.md
├── migrations/                      # Alembic: the employees table
│   ├── env.py
│   └── versions/
├── alembic.ini
├── .env.example                     # every setting, with placeholders
├── apitest.py                       # 94-check live API conformance test
├── train_model.py
└── README.md
```

## Notes on the model

Fuel and emission factors are indicative tank-to-wake figures in the range used
by IMO MEPC guidance; bunker prices are 2024–25 order-of-magnitude values. They
are defaults meant to be replaced with real operator data — everything derives
from one table in `backend/data/fuel_database.py`, so changing them there
updates the optimizer, the scenario analyser and the UI together.

## License

MIT
