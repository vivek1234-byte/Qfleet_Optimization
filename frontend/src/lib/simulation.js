/**
 * Turning API responses into something the simulator can sail.
 *
 * Two sources feed the map:
 *   - an optimiser result, whose `plan.assignments` already carry the speed,
 *     fuel, distance and per-vessel fuel/CO2/cost the solver settled on;
 *   - the bare registry, used before anything has been optimised, where the
 *     vessels sail at design speed on their home lanes.
 *
 * The second case needs per-voyage figures of its own, so `estimateVoyage`
 * mirrors the backend's physics. The constants below are the same ones in
 * `backend/optimization/fleet_problem.py`; if those change, change these.
 */

const BASE_SFC_G_PER_KWH = 175.0
const VESSEL_OPEX_USD_PER_DAY = 9_500.0

/** Deterministic 0..1 from a string, so the staggered start is stable. */
function hashUnit(text) {
  let h = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return ((h >>> 0) % 10000) / 10000
}

/**
 * Sea-leg fuel, CO2 and cost for one voyage.
 *
 * `fuel` is a row from /api/scenarios/fuels. This is a mirror of the
 * optimiser's `_voyage_terms`, not an independent model — the point is that an
 * un-optimised vessel on the map burns fuel on the same basis as an optimised
 * one, so the comparison is fair.
 */
export function estimateVoyage({ ratedKw, designSpeed, speedKnots, distanceNm, beaufort, loadPct, fuel }) {
  const hours = distanceNm / Math.max(speedKnots, 0.1)
  const powerKw = Math.min(ratedKw * (speedKnots / Math.max(designSpeed, 0.1)) ** 3, ratedKw)
  const weather = 1 + 0.02 * Math.pow(Math.max(beaufort, 0), 1.5)
  const load = Math.pow(Math.max(loadPct, 1) / 100, 0.7)
  const sfc = BASE_SFC_G_PER_KWH * (fuel?.sfc_multiplier ?? 1)

  const fuelTons = ((powerKw * sfc) / 1e6) * hours * weather * load
  const energyMj = fuelTons * 1000 * (fuel?.energy_density_mj_per_kg ?? 40.2)
  const co2Tons = (energyMj * (fuel?.emission_factor_gco2_per_mj ?? 77.4)) / 1e6
  const bunkerUsd = fuelTons * (fuel?.cost_per_ton ?? 500)
  const opexUsd = (hours / 24) * VESSEL_OPEX_USD_PER_DAY

  return { hours, fuelTons, co2Tons, costUsd: bunkerUsd + opexUsd, powerKw }
}

/** Build simulator ships from an optimiser result. */
export function shipsFromPlan(result, lanesByName) {
  const assignments = result?.plan?.assignments
  if (!assignments?.length) return []

  return assignments.map((a, index) => {
    const lane = lanesByName[a.route_name]
    return {
      id: `plan-${a.vessel_id}-${index}`,
      vesselId: a.vessel_id,
      vesselName: a.vessel_name,
      vesselType: a.vessel_type,
      laneName: a.route_name,
      originName: lane?.origin ?? '',
      destinationName: lane?.destination ?? '',
      fuelType: a.fuel_type,
      speedKnots: a.speed_knots,
      shorePowerPct: a.shore_power_pct,
      distanceNm: a.distance_nm,
      voyageDays: a.voyage_days,
      fuelTons: a.fuel_tons,
      co2Tons: a.co2_tons,
      costUsd: a.cost_usd,
      // Spread departures so the fleet is not a single convoy leaving together.
      phaseHours: hashUnit(`${a.vessel_name}|${a.route_name}`) * 24 * 14,
    }
  })
}

/**
 * A plausible pre-optimisation fleet, for the map before anything is run.
 *
 * Vessels are matched to lanes by class — boxes for container ships, ore and
 * fertiliser for bulkers, crude and products for tankers — and sail at design
 * speed on today's default bunker, which is what the optimiser is measured
 * against.
 */
export function shipsFromRegistry(registry, fuelsByName, { limit = 14 } = {}) {
  const vessels = registry?.vessels ?? []
  const lanes = registry?.lanes ?? []
  if (!vessels.length || !lanes.length) return []

  const CARGO_FOR_TYPE = {
    Container: (lane) => /container|box/i.test(lane.cargo),
    'Bulk Carrier': (lane) => /ore|bulk|fertiliser|steel/i.test(lane.cargo),
    Tanker: (lane) => /crude|product/i.test(lane.cargo),
  }
  const DEFAULT_FUEL = { Container: 'VLSFO', 'Bulk Carrier': 'HFO', Tanker: 'VLSFO' }

  const counters = {}
  return vessels.slice(0, limit).map((vessel, index) => {
    const match = CARGO_FOR_TYPE[vessel.vessel_type] ?? (() => true)
    const candidates = lanes.filter(match)
    const pool = candidates.length ? candidates : lanes
    const n = counters[vessel.vessel_type] ?? 0
    counters[vessel.vessel_type] = n + 1
    const lane = pool[n % pool.length]

    const fuelName = DEFAULT_FUEL[vessel.vessel_type] ?? 'VLSFO'
    const fuel = fuelsByName?.[fuelName]
    const speed = vessel.design_speed_knots
    const loadPct = 78
    const estimate = estimateVoyage({
      ratedKw: vessel.rated_power_kw,
      designSpeed: vessel.design_speed_knots,
      speedKnots: speed,
      distanceNm: lane.distance_nm,
      beaufort: lane.typical_beaufort,
      loadPct,
      fuel,
    })

    return {
      id: `reg-${index}`,
      vesselId: index,
      vesselName: vessel.name,
      vesselType: vessel.vessel_type,
      laneName: lane.name,
      originName: lane.origin,
      destinationName: lane.destination,
      fuelType: fuelName,
      speedKnots: speed,
      shorePowerPct: 0,
      distanceNm: lane.distance_nm,
      voyageDays: estimate.hours / 24,
      fuelTons: estimate.fuelTons,
      co2Tons: estimate.co2Tons,
      costUsd: estimate.costUsd,
      phaseHours: hashUnit(`${vessel.name}|${lane.name}`) * 24 * 14,
    }
  })
}

/** Format a simulated clock reading as "Day 3, 14:20". */
export function formatSimClock(hours) {
  if (!Number.isFinite(hours)) return 'Day 1, 00:00'
  const totalMinutes = Math.floor(hours * 60)
  const day = Math.floor(totalMinutes / 1440) + 1
  const minuteOfDay = totalMinutes % 1440
  const hh = String(Math.floor(minuteOfDay / 60)).padStart(2, '0')
  const mm = String(minuteOfDay % 60).padStart(2, '0')
  return `Day ${day}, ${hh}:${mm}`
}

/** Human duration from hours: "2 d 6 h" / "14 h" / "40 min". */
export function formatDuration(hours) {
  if (!Number.isFinite(hours) || hours < 0) return '—'
  if (hours < 1) return `${Math.round(hours * 60)} min`
  if (hours < 48) return `${hours.toFixed(1)} h`
  const days = Math.floor(hours / 24)
  return `${days} d ${Math.round(hours - days * 24)} h`
}

/** Clock speed presets, in simulated hours per real second. */
export const TIME_SCALES = [
  { id: 'realtime', label: 'Real time', hoursPerSecond: 1 / 3600, note: '1 s = 1 s' },
  { id: 'fast', label: '1 h/s', hoursPerSecond: 1, note: '1 s = 1 hour' },
  { id: 'faster', label: '6 h/s', hoursPerSecond: 6, note: '1 s = 6 hours' },
  { id: 'fastest', label: '1 d/s', hoursPerSecond: 24, note: '1 s = 1 day' },
]
