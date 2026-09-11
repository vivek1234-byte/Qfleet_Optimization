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
| `/` | Dashboard — system health, model quality, one-click live optimisation |
| `/simulator` | **Live voyage simulator** — vessels moving on the real lane network |
| `/optimize` | Configure and run a solver; plan, Pareto front, convergence, comparison |
| `/predict` | Fuel prediction, speed sensitivity, fuel-by-fuel comparison, model card |
| `/fleet` | The 20-vessel registry and the 16 trade lanes |
| `/scenarios` | Fuel comparison, transition plan, shore power, fuel reference |
| `/benchmarks` | Multi-seed solver benchmarks, scalability, metric definitions |

Every endpoint the API exposes is reachable from one of these.

## The simulator

`src/pages/Simulator.jsx` is the centrepiece; the pieces it is built from are
worth knowing about.

**The map is inline SVG, drawn from baked-in data.** `src/data/land.js` holds
Natural Earth 1:110m coastlines (public domain) projected equirectangularly and
simplified to about 60 kB of path data. `src/data/geography.js` holds the port
positions and the sea waypoints for each lane — Bab-el-Mandeb and the Suez Canal
for Europe, the Malacca Strait for East Asia, the Mozambique Channel for Durban,
and round Dondra Head rather than through the Palk Strait for Colombo. Segment
lengths are rescaled so the drawn polyline sums to the registry's published sea
distance, which keeps a vessel's position on screen and its progress percentage
in agreement.

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
  components/   AppShell, ui.jsx primitives, themed Recharts wrappers,
                WorldMap (base map + pan/zoom), ShipLayer (animation)
  data/         land.js (coastlines), geography.js (ports, lanes, projection)
  hooks/        useApi (useAsync/useFetch/usePolling), useTheme
  lib/          api.js (every endpoint), domain.js (fuel colours, presets),
                format.js, nav.js, planStore.js, simulation.js
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
- No browser storage beyond the theme preference.
