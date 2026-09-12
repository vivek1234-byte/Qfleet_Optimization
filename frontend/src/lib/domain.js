/**
 * Shared vocabulary for the maritime domain: fuel colours, vessel silhouettes,
 * and the demo presets the optimiser and simulator both offer.
 *
 * Fuel colour is the single most reused encoding in the app — it identifies a
 * vessel on the map, a slice in the mix chart and a row in the plan table — so
 * it lives here rather than being redefined per page.
 */

export const FUEL_COLORS = {
  HFO: '#6b7280',
  VLSFO: '#0ea5e9',
  MGO: '#f59e0b',
  LNG: '#22d3ee',
  Methanol: '#a78bfa',
  Ammonia: '#34d399',
  Hydrogen: '#f472b6',
}

export const FUEL_ORDER = ['HFO', 'VLSFO', 'MGO', 'LNG', 'Methanol', 'Ammonia', 'Hydrogen']

export const fuelColor = (name) => FUEL_COLORS[name] ?? '#94a3b8'

/** Short blurb per fuel, for tooltips where the table is not on screen. */
export const FUEL_NOTES = {
  HFO: 'Cheapest and dirtiest. Only legal outside emission control areas with scrubbers.',
  VLSFO: 'The post-2020 sulphur-cap default. Todays baseline bunker.',
  MGO: 'Distillate. Clean-burning, used inside ECAs, noticeably dearer.',
  LNG: 'Around a quarter less CO₂ and no SOₓ, but needs cryogenic tanks and a retrofit.',
  Methanol: 'Drop-in-ish liquid, easy to bunker, green only if the methanol is green.',
  Ammonia: 'Zero carbon at the stack. Toxic, and the engines are only now arriving.',
  Hydrogen: 'Zero carbon at the stack. Storage volume and availability are the blockers.',
}

/* -------------------------------------------------------------------------- */
/* Vessel silhouettes                                                          */
/* -------------------------------------------------------------------------- */
/**
 * Plan-view hull outlines drawn bow-up in a 10x26 box centred on the origin,
 * so a marker only needs `rotate(heading)`.
 */
export const VESSEL_SHAPES = {
  Container: 'M0 -13 L3.4 -6 L3.4 10 L2.2 13 L-2.2 13 L-3.4 10 L-3.4 -6 Z',
  'Bulk Carrier': 'M0 -12 L3.8 -5 L3.8 11 L2.4 13 L-2.4 13 L-3.8 11 L-3.8 -5 Z',
  Tanker: 'M0 -12.5 L3.6 -5.5 L3.6 10.5 L2 13 L-2 13 L-3.6 10.5 L-3.6 -5.5 Z',
}

export const vesselShape = (type) => VESSEL_SHAPES[type] ?? VESSEL_SHAPES.Container

/** Deck detail so the three classes read differently at a glance. */
export const VESSEL_DECK = {
  Container: [
    { x: -2.6, y: -4, w: 5.2, h: 10, r: 0.4 },
    { x: -1.8, y: 6.6, w: 3.6, h: 4, r: 0.5 },
  ],
  'Bulk Carrier': [
    { x: -2.8, y: -3, w: 5.6, h: 3.2, r: 0.4 },
    { x: -2.8, y: 1.2, w: 5.6, h: 3.2, r: 0.4 },
    { x: -2, y: 7.4, w: 4, h: 3.6, r: 0.5 },
  ],
  Tanker: [
    { x: -2.6, y: -3.5, w: 5.2, h: 9.5, r: 2.2 },
    { x: -1.9, y: 7.2, w: 3.8, h: 3.8, r: 0.5 },
  ],
}

export const vesselDeck = (type) => VESSEL_DECK[type] ?? VESSEL_DECK.Container

export const VESSEL_TYPE_COLORS = {
  Container: '#06a3ee',
  'Bulk Carrier': '#f59e0b',
  Tanker: '#a78bfa',
}

/* -------------------------------------------------------------------------- */
/* Weather                                                                     */
/* -------------------------------------------------------------------------- */
/** Beaufort description, used on lane cards and the map legend. */
export function beaufortLabel(value) {
  if (!Number.isFinite(value)) return '—'
  if (value < 3) return 'Light breeze'
  if (value < 4) return 'Gentle breeze'
  if (value < 5) return 'Moderate breeze'
  if (value < 6) return 'Fresh breeze'
  if (value < 7) return 'Strong breeze'
  return 'Near gale'
}

/** Warm-to-cool ramp for typical sea state on a lane. */
export function beaufortColor(value) {
  if (!Number.isFinite(value)) return '#64748b'
  if (value < 4.0) return '#34d399'
  if (value < 4.4) return '#a3e635'
  if (value < 4.7) return '#fbbf24'
  return '#fb7185'
}

/* -------------------------------------------------------------------------- */
/* Presets                                                                     */
/* -------------------------------------------------------------------------- */
/**
 * Objective weights for the single-objective solvers: `[fuel, CO₂, cost]`.
 *
 * Operating cost is what this platform is for, so the solver is told that.
 * The figure is not a guess — QGA at 20×16, 400 iterations, population 100,
 * measured over six seeds (1, 7, 13, 42, 99, 2024) against the un-optimised
 * registry fleet, comparing per-nautical-mile intensity:
 *
 * | weights            | cost saved        | fuel  | CO₂e  |
 * |--------------------|-------------------|-------|-------|
 * | 0.4 / 0.4 / 0.2    | 32.4% (worst 29.3)| 43.7% | 60.5% |
 * | equal thirds       | 33.7% (worst 29.6)| 44.8% | 58.7% |
 * | **0.25/0.25/0.5**  | **34.7% (worst 32.2)** | **44.5%** | **58.9%** |
 * | 0.17/0.17/0.67     | 35.2% (worst 31.9)| 43.4% | 50.2% |
 * | 0 / 0 / 1          | 36.0% (worst 31.9)| 41.6% | 47.1% |
 *
 * Every run feasible, ~1.9 s. Half-weight on cost is where the curve turns:
 * it buys the largest cost saving that costs nothing in emissions, and lifts
 * the *worst* seed from 29.3% to 32.2%, which is what matters when the run
 * happens live. Past it the trade goes bad fast — pricing cost alone gives up
 * 11.6 points of CO₂ to gain 1.3 points of cost, and a green-fleet platform
 * that quietly buys cheap dirty bunker to win on price has argued itself out
 * of its own premise.
 *
 * The Optimizer page's sliders start here and can be moved; this is the
 * default the one-click runs on the Dashboard and the twin send.
 */
export const COST_FIRST_WEIGHTS = [0.25, 0.25, 0.5]

/**
 * Three sizes with an honest note on what each costs to run. The demo preset
 * exists because a live run on stage has to finish while the presenter is
 * still mid-sentence.
 */
export const OPTIMIZER_PRESETS = [
  {
    id: 'demo',
    name: 'Demo',
    hint: 'Sub-second. Use this on stage.',
    config: { n_vessels: 8, n_routes: 5, max_iterations: 80, population_size: 40 },
  },
  {
    id: 'standard',
    name: 'Standard',
    hint: 'A realistic mid-size operator. A second or two.',
    config: { n_vessels: 15, n_routes: 8, max_iterations: 150, population_size: 60 },
  },
  {
    id: 'stress',
    name: 'Full fleet',
    hint: 'Every vessel and lane in the registry. Slower — NSGA-II especially.',
    config: { n_vessels: 20, n_routes: 12, max_iterations: 250, population_size: 100 },
  },
]

/** Vessel-type presets for the prediction form. */
export const PREDICTION_PRESETS = [
  {
    id: 'container',
    label: 'Container · JNPT → Singapore',
    values: {
      vessel_type: 'Container',
      dwt: 92000,
      engine_power_kw: 44000,
      speed_knots: 18,
      distance_nm: 2450,
      cargo_load_pct: 82,
      weather_beaufort: 4.4,
      draft_meters: 13.5,
      fuel_type: 'VLSFO',
    },
  },
  {
    id: 'bulk',
    label: 'Bulk carrier · Paradip → Qingdao',
    values: {
      vessel_type: 'Bulk Carrier',
      dwt: 82000,
      engine_power_kw: 12500,
      speed_knots: 13,
      distance_nm: 3900,
      cargo_load_pct: 90,
      weather_beaufort: 4.7,
      draft_meters: 14.2,
      fuel_type: 'HFO',
    },
  },
  {
    id: 'tanker',
    label: 'Tanker · Kandla → Jeddah',
    values: {
      vessel_type: 'Tanker',
      dwt: 115000,
      engine_power_kw: 17500,
      speed_knots: 14,
      distance_nm: 1720,
      cargo_load_pct: 95,
      weather_beaufort: 4.0,
      draft_meters: 15.0,
      fuel_type: 'MGO',
    },
  },
]

/* -------------------------------------------------------------------------- */
/* Algorithms                                                                  */
/* -------------------------------------------------------------------------- */
export const ALGORITHM_COLORS = {
  qpso: '#06a3ee',
  qga: '#a78bfa',
  pso: '#f59e0b',
  nsga2: '#15af73',
}

export const algorithmColor = (id) => ALGORITHM_COLORS[id] ?? '#64748b'

/* -------------------------------------------------------------------------- */
/* Regulatory                                                                  */
/* -------------------------------------------------------------------------- */
/**
 * IMO carbon intensity rating bands.
 *
 * A and B are superior, C meets the requirement, D three years running or E
 * once forces a corrective action plan — so the colour break belongs between
 * C and D, not in the middle of the scale.
 */
export const CII_COLORS = {
  A: '#15af73',
  B: '#65c97f',
  C: '#f5c451',
  D: '#f38b4a',
  E: '#ef4444',
}

export const CII_BANDS = ['A', 'B', 'C', 'D', 'E']

export const ciiColor = (band) => CII_COLORS[band] ?? '#64748b'

/** Badge tone for a rating, for the shared Badge component. */
export const ciiTone = (band) =>
  band === 'A' || band === 'B' ? 'eco' : band === 'C' ? 'warning' : 'danger'

export const ciiCompliant = (band) => band === 'A' || band === 'B' || band === 'C'

export const MONTHS = [
  { value: 1, label: 'January', short: 'Jan' },
  { value: 2, label: 'February', short: 'Feb' },
  { value: 3, label: 'March', short: 'Mar' },
  { value: 4, label: 'April', short: 'Apr' },
  { value: 5, label: 'May', short: 'May' },
  { value: 6, label: 'June', short: 'Jun' },
  { value: 7, label: 'July', short: 'Jul' },
  { value: 8, label: 'August', short: 'Aug' },
  { value: 9, label: 'September', short: 'Sep' },
  { value: 10, label: 'October', short: 'Oct' },
  { value: 11, label: 'November', short: 'Nov' },
  { value: 12, label: 'December', short: 'Dec' },
]

/** Colour for a seasonal weather multiplier: calm green to rough red. */
export function seasonColor(factor) {
  if (!Number.isFinite(factor)) return '#64748b'
  if (factor < 0.9) return '#15af73'
  if (factor < 1.0) return '#84cc16'
  if (factor < 1.15) return '#f5c451'
  if (factor < 1.3) return '#f38b4a'
  return '#ef4444'
}

/** What-if sandbox levers, so the page and its reset button agree. */
export const SANDBOX_DEFAULTS = {
  carbon_price_usd_per_ton: 0,
  speed_cap_knots: '',
  month: '',
  n_vessels: 12,
  n_routes: 7,
  max_iterations: 120,
  population_size: 50,
  algorithm: 'qpso',
  seed: 42,
}
