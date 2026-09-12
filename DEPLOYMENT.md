# Deploying QFleet

Two halves, two hosts, one afternoon:

| Half | Host | Why |
|---|---|---|
| `frontend/` — React/Vite bundle | **Vercel** | Static files on a CDN. What Vercel is for. |
| `backend/` — FastAPI, optimiser, ML | **Render** (Docker) | Vercel cannot host it: see below. |

## Why the API does not go on Vercel

Not a preference — two hard limits.

**Size.** The dependency tree unzips to roughly 600 MB (numpy, pandas, scipy, scikit-learn, xgboost), and that is *after* pinning xgboost below 3.0 to shed the 454 MB of CUDA runtime its 3.x wheel drags in. A Vercel Python function may be 250 MB uncompressed. Cutting it to fit means dropping the Fuel Prediction page.

**State.** Vercel's filesystem is read-only apart from a per-instance `/tmp` that evaporates. Signing in writes to the database — last-login, the audit log, token versions — so authentication fails on a read-only disk, and the employee admin screen would have nothing to write to.

Any host that runs a container is fine. Render is specified here; Fly.io, Railway, Koyeb and Hugging Face Spaces all take the same `Dockerfile` unchanged.

---

## 1. Backend on Render

Everything Render needs is in `render.yaml` and `Dockerfile`, both committed at the repository root.

1. Push this branch to GitHub.
2. Render dashboard → **New → Blueprint** → pick the `Qfleet_Optimization` repo. It reads `render.yaml` and offers one service, `qfleet-api`.
3. It will ask for the two variables marked `sync: false`:
   - `QGF_CORS_ORIGINS` — leave blank for now; the Vercel URL does not exist yet.
   - `QGF_DATABASE_URL` — leave blank to use SQLite inside the container.
4. **Apply**. First build is 5–8 minutes, mostly pip.

Render's CLI is for logs and shells rather than creating services from a blueprint, so that part is the dashboard. After it exists, every `git push` redeploys it automatically.

Note the URL it gives you — `https://qfleet-api.onrender.com` or similar. Check it:

```bash
curl https://qfleet-api.onrender.com/api/health
# {"status":"healthy","checks":{"api":...,"accounts":...,"prediction_model":...,"dataset":...}}
```

All four checks should read `true`. `prediction_model` is true because the image trains it at build time; nothing to do by hand.

## 2. Frontend on Vercel

From the repository root:

```bash
cd frontend
npx vercel login
npx vercel link                       # creates the project; accept the defaults

# The API URL is compiled into the bundle, so it must exist before the build.
# Paste the Render URL with no trailing slash.
npx vercel env add VITE_API_BASE_URL production
# → https://qfleet-api.onrender.com

npx vercel --prod
```

Vercel prints the production URL. `frontend/vercel.json` already sets the Vite framework preset, the `dist` output directory, the single-page rewrite (so a refresh on `/simulator` is not a 404) and a one-year cache on the fingerprinted assets.

## 3. Let them talk to each other

The API refuses cross-origin requests from anywhere it has not been told about — that is the CORS check doing its job, and until you do this, login fails with a console error and nothing else.

Render dashboard → `qfleet-api` → **Environment** → set:

```
QGF_CORS_ORIGINS = https://your-project.vercel.app
```

No trailing slash; browsers compare origins exactly. Comma-separate if you add a custom domain later. Save — Render restarts the service — then load the Vercel URL and sign in with `ADMIN001` / `Admin@12345`.

---

## Before the judges see it

**Wake the backend first.** Render's free tier sleeps a service after 15 minutes of no traffic, and the next request pays a cold start of roughly a minute while the container boots and loads the numeric stack. Open the site — or `curl` the health endpoint — a few minutes before you present. If a minute of blank screen during judging is not a risk you want, Render's Starter plan is $7/month and never sleeps.

**The demo logins are public.** `QGF_SEED_DEMO=true` creates `ADMIN001` / `EMP001` with the passwords printed in this repository, so anyone who reads it can sign in as an administrator on your deployment. That is the trade for a working demo. Afterwards:

```bash
# create a real administrator, then turn the seed off
python -m backend.manage bootstrap
```
and set `QGF_SEED_DEMO=false` on Render.

**Accounts reset when the container restarts.** With SQLite the database lives inside the container, so a sleep/wake cycle takes any employee you added through the admin screen with it. The seeded demo accounts come back on every boot, so logins keep working — it is only changes that are lost. If you want them to survive, create a free Postgres (Neon, or Render's own) and set:

```
QGF_DATABASE_URL = postgresql+psycopg://user:password@host/dbname
```

The driver is already in the image; nothing is rebuilt.

**One repository tidy-up.** `backend/data/qfleet.db-shm` and `-wal` are committed leftovers from a laptop's SQLite session — a write-ahead log with no database behind it. The Dockerfile deletes them, but they should not be in git at all:

```bash
git rm --cached backend/data/qfleet.db-shm backend/data/qfleet.db-wal
```

---

## What was verified before this was written

Against a clean database, with the frontend built exactly as Vercel builds it and served from a different origin than the API:

- entrypoint runs migrations from empty to `0005_renumber_ids`, seeds the five demo accounts, serves — and on restart reports "Already present, left alone" rather than duplicating anyone;
- `/api/health` returns `healthy` on all four checks, prediction model included;
- CORS preflight from the configured origin returns 200 with `access-control-allow-origin`; from any other origin, 400;
- cross-origin login succeeds and the app lands on the twin with fleet data rendered;
- a deep link to `/simulator` resolves rather than 404ing;
- the Fuel Prediction page finds a trained model;
- no console errors anywhere in the run.

The one thing not verified here is the Docker build itself — this sandbox has no Docker daemon. Every layer in it is a standard `python:3.11-slim` step, and the entrypoint it ends in was run directly against the same source.
