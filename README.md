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
consumption, weather and cargo-load correction, port hotel load offset by shore
power, and constraints for route demand coverage, schedule windows, bunker tank
range and fuel availability. Every solver is warm-started from a feasible
baseline plan, so a run can never report a result worse than doing nothing.

## Tech stack

- **Backend** — Python 3.9+, FastAPI, Uvicorn, Pydantic v2
- **Optimisation** — NumPy (fully vectorised), pymoo for quality indicators
- **ML** — scikit-learn, XGBoost, optional PyTorch
- **Frontend** — React 19, Vite, Tailwind, Recharts, and a hand-built inline-SVG
  chart of the world for the voyage simulator (no map library, no tile server)

## The web interface

`frontend/` is a seven-page application covering every endpoint the API
exposes. The one worth opening first is **Live Simulator**: the fleet sails the
real Indian trade-lane network — through Suez, Bab-el-Mandeb, Hormuz and
Malacca — in accelerated time, coloured by fuel, with fuel burnt, CO2 emitted
and voyage cost ticking up live. Run the optimiser and the same vessels
redeploy onto the plan the solver produced.

Everything it needs is bundled: coastlines, routes, fonts, styles. It makes no
network call except to this API, which matters when the venue Wi-Fi does not
work. See `frontend/README.md` for the details.

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


## Tests

```bash
cd backend
python -m pytest tests -q
```

129 tests covering the fleet model, all four solvers, the prediction pipeline,
the fuel database, the quality indicators and every API route — including
regression tests pinning the specific bugs this version fixed.

## Project structure

```
quantum-green-fleet/
├── backend/
│   ├── config.py                    # settings and guard rails
│   ├── main.py                      # FastAPI app, middleware, error handlers
│   ├── core/errors.py               # typed application errors
│   ├── data/
│   │   ├── fuel_database.py         # single source of truth for fuel properties
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
│   │   ├── lib/                     # api.js, domain.js, simulation.js, …
│   │   └── pages/                   # one file per route
│   ├── vite.config.js               # proxies /api to the backend
│   └── README.md
├── apitest.py                       # 61-check live API conformance test
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
