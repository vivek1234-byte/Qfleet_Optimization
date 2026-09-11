# QFleet — web interface

React 19 + Vite + Tailwind. Talks to the FastAPI backend and nothing else: no
third-party services, no map tiles, no fonts fetched at runtime. Everything the
UI needs is in the bundle, because a hackathon venue's Wi-Fi is not a dependency
worth taking.

## Running it

From the project root, `start.bat` (Windows) or `./start.sh` (macOS/Linux)
brings up the API and this UI together. To run just the UI against an API that
is already up:

```bash
npm install
npm run dev          # http://localhost:5173
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so the browser only
ever talks to one origin and there is no CORS to go wrong. Point it somewhere
else with `VITE_PROXY_TARGET`, or build against an absolute API host with
`VITE_API_BASE_URL` (see `.env.example`).

```bash
npm run build        # production bundle into dist/
npm run preview      # serve dist/ — needs the API on the same origin
npm run lint         # oxlint
```

## Pages

| Route | What it is |
| --- | --- |
| `/login` | Sign-in — Employee ID and password |
| `/` | Dashboard — system health, model quality, one-click live optimisation |
| `/simulator` | **Live voyage simulator**, with a split baseline-vs-optimised mode |
| `/sandbox` | **What-if sandbox** — move a lever, watch the solver re-run over SSE |
| `/optimize` | Configure and run a solver; plan, Pareto front, convergence, comparison |
| `/compliance` | **CII ratings, emission control areas, seasonal weather** |
| `/predict` | Fuel prediction, speed sensitivity, fuel-by-fuel comparison, model card |
| `/fleet` | The 20-vessel registry and the 16 trade lanes |
| `/scenarios` | Fuel comparison, transition plan, shore power, fuel reference |
| `/benchmarks` | Multi-seed solver benchmarks, scalability, metric definitions |
| `/admin` | **Employees** — accounts and access. Administrators only, and deliberately not in the sidebar: reach it by URL |

Every endpoint the API exposes is reachable from one of these.

## Sign-in

`/login` takes an **Employee ID and a password** and posts them to
`/api/auth/login`, which checks them against the `employees` table. A
successful sign-in returns a token; `src/lib/auth.js` holds it and
`src/lib/api.js` attaches it to every request as `Authorization: Bearer …`.
Everything below `/login` sits behind `RequireAuth`, which remembers where you
were heading and returns you there afterwards.

Four things are worth knowing before changing any of it:

- **A stored token is revalidated, not trusted.** `App.jsx` calls
  `revalidate()` once on load and `RequireAuth` renders nothing until it
  answers. Without that, an account deactivated this morning keeps a
  working-looking dashboard until its token expires tonight.
- **A 401 on any request ends the session.** The response interceptor calls
  `sessionExpired`, so the user lands back on `/login` with a reason rather
  than on a page whose every request quietly fails. `skipAuthRedirect` opts
  out, for the login call itself — a 401 there means "wrong password", not
  "your session ended".
- **The role in the session is presentation only.** It decides whether the
  Employees link renders. It decides nothing about what the API will allow:
  `/api/admin/*` is behind `require_admin` on the server, so editing the
  stored role in devtools gets you a link that returns 403.
- **The failure message is identical for a wrong password and an unknown
  Employee ID**, and the client adds no format validation that would give the
  difference away. That is deliberate; see `backend/auth/api.py`.

Persistence follows the "remember me" box: localStorage when ticked so the
session outlives the tab, sessionStorage when not.

The chart panel is drawn from the same bundled Natural Earth coastline the maps
use, so the sign-in screen renders with the backend down — verified: it makes
zero API calls until you press Sign in.

## Employees (`/admin`)

Administrators only, enforced by `RequireAdmin` in the router and by
`require_admin` on the server. It is **not in the sidebar** — the nav entry
carries `hidden: true`, so `navItemsFor` drops it for everyone while the route
and the header title keep working. Add, search, edit, reset a password,
deactivate, delete.
Nothing here can read a password back — the API returns no hash, ever — so the
form is write-only and "reset" is the whole recovery story.

## Split comparison

The simulator's split mode puts the unoptimised fleet and the solver's plan on
two maps side by side, **sharing one clock and one viewport** — pan either and
both move, so the comparison cannot quietly drift. The divergence counter
underneath compares *per vessel*, not per fleet: the two sides can carry
different numbers of ships, and raw totals would flatter whichever has fewer.

Sharing a viewport is why `useMapViewport` owns only the viewBox. Anything
measured in pixels belongs to the individual map — each `WorldMap` runs its own
`ResizeObserver` and publishes `pxPerUnit` through `MapMetricsContext`, which is
how `ShipLayer` keeps vessel markers the same size in a half-width pane. An
earlier version kept the DOM ref in the shared hook; the second map to mount
overwrote the first, so markers came out half-size and dragging the left pane
computed its offset from the right pane's rectangle.

## Streaming

`/sandbox` consumes `GET /api/optimization/stream` with `EventSource`: one
`progress` frame per solver iteration, then `done` with the full result. The
convergence curve draws itself as the search happens rather than appearing
complete at the end. `streamOptimization` in `src/lib/api.js` returns a `close`
function — call it on unmount, or the browser holds the connection and the
solver thread behind it open after the user navigates away. Auto-solve is
debounced, because dragging a slider fires a change per pixel and each one
would otherwise start a solver.

## The simulator

`src/pages/Simulator.jsx` is the centrepiece; the pieces it is built from are
worth knowing about.

**The map is inline SVG, drawn from baked-in coastlines and API geometry.**
`src/data/land.js` holds Natural Earth 1:110m coastlines (public domain)
projected equirectangularly and simplified to about 60 kB of path data — no tile
server, no map library, no network call. The routes themselves come from the
API: ports, waypoints and cumulative distances arrive with
`/api/optimization/registry`, because the backend needs the same geometry to
work out emission-control-area exposure, and a route drawn from one source while
priced from another is a bug waiting to happen. `src/data/geography.js` is now
just the projection and the interpolation the animation needs sixty times a
second.

**The animation does not go through React.** Twenty vessels at 60 fps would be
1,200 component renders a second. `src/components/ShipLayer.jsx` runs one
`requestAnimationFrame` loop that writes SVG transforms straight onto the DOM
nodes, and pushes a snapshot into React state four times a second for the side
panel. Markers stay a constant pixel size at every zoom level.

**The figures are the optimiser's, not the simulator's.** Fuel, CO₂ and cost per
vessel come from `plan.assignments` and are apportioned by distance sailed, so
the live ticker and the plan table can never disagree. Before anything has been
optimised the map shows the registry fleet at design speed, and *that* case is
estimated locally — `estimateVoyage` in `src/lib/simulation.js` mirrors the
backend's cubic speed-power law, Beaufort factor and load factor so the
comparison against an optimised plan is like for like. If the backend's physics
changes, change that function too.

## Layout

```
src/
  components/   AppShell, RequireAuth, ui.jsx primitives, Recharts wrappers,
                WorldMap (base map, ECA layer, pan/zoom, map metrics),
                VoyageMap (a map with ships on it), ShipLayer (animation)
  data/         land.js (coastlines), geography.js (projection + interpolation)
  hooks/        useApi (useAsync/useFetch/usePolling), useNetwork, useTheme
  lib/          api.js (every endpoint, the SSE client, the bearer-token
                interceptor), auth.js (the session and the sign-in call),
                nav.js (role-gated navigation), domain.js (fuel and
                CII colours, presets), format.js, nav.js, planStore.js,
                simulation.js
  pages/        one file per route
```

`src/lib/api.js` is the only place that knows a URL. It normalises the backend's
error envelope into an `ApiError` carrying a code and per-field messages, which
is what lets forms show an inline message on a 422 instead of a generic failure.

## Conventions worth keeping

- Colour is meaning: a fuel is always the same colour, in the map legend, the
  mix chart and the plan table. `fuelColor()` in `src/lib/domain.js`.
- Theming is CSS custom properties in `src/index.css`, not `dark:` classes
  sprinkled through components. Charts read the same variables.
- Do not use `?? []` inline for API data. A fresh array every render
  invalidates every `useMemo` downstream — the pages use a module-level
  `EMPTY` constant instead.
- Map pages take their network from `useNetwork()`, which fetches the registry
  and the ECA zones once and memoises the derived lane geometries. Building
  those per render on a page that animates at 60 fps is the expensive mistake.
- No browser storage beyond the theme preference.

## Known backend quirks the UI works around

- `POST /api/optimization/compare` rejects `objective_weights` and
  `speed_cap_knots`; both are stripped before the call.
- `POST /api/prediction/predict/batch` returns bare tonnages, not prediction
  objects. CO₂ and cost for the fuel sweep are derived from the fuel database,
  and the confidence band on the speed sweep is ±1.96 × the model's RMSE.
- `best_objectives` is not always byte-identical to a `pareto_front` member, so
  the knee point is marked by nearest normalised distance rather than equality.
