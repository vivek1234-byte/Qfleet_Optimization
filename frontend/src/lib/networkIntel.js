/**
 * Network intelligence, derived from the deployment plan.
 *
 * Every figure the Network section shows comes from here, and every figure
 * here is computed from data the backend actually produces — the registry
 * (`/api/optimization/registry`), the baseline deployment
 * (`/api/optimization/fleet`) and, once the user has run one, the optimised
 * plan in `planStore`.
 *
 * **Nothing in this file invents a number.** That matters more than it
 * sounds: a dashboard full of plausible percentages is worse than one with
 * gaps, because the first time someone asks "where does 94.7% come from?"
 * the answer has to be a data source, not a shrug. Where the project has no
 * source for something — port arrivals and departures, berth turnaround,
 * live traffic congestion — the metric is absent rather than filled in, and
 * `UNAVAILABLE` records why so the UI can say so.
 *
 * The one honest substitution worth naming: what a traffic dashboard would
 * call *congestion*, this calls **schedule pressure** — how much of a lane's
 * contractual transit window the planned voyage actually consumes. That is a
 * real constraint in `fleet_registry.LaneSpec.max_transit_days`, it behaves
 * like congestion (high means the lane has no slack), and it does not pretend
 * to know about other people's ships.
 */

/** Metrics a maritime operations centre would show that this project has no source for. */
export const UNAVAILABLE = {
  arrivals: 'No schedule or AIS feed — arrivals are not modelled',
  departures: 'No schedule or AIS feed — departures are not modelled',
  turnaround: 'No port call records — berth turnaround is not modelled',
  congestion: 'No live traffic feed — see schedule pressure instead',
}

const EMPTY = []
const round = (value, places = 1) => {
  const factor = 10 ** places
  return Math.round((Number(value) || 0) * factor) / factor
}
const mean = (values) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0)

/* -------------------------------------------------------------------------- */
/* Lane state                                                                  */
/* -------------------------------------------------------------------------- */
/**
 * Four states, each with a real definition:
 *
 * - `optimised` — the optimiser moved this lane somewhere better than the
 *   baseline. Only ever set when an optimised plan exists to compare against.
 * - `pressure` — the planned voyage eats 90%+ of the lane's contractual
 *   transit window (`max_transit_days`). No slack for weather or a delay.
 * - `intensive` — fuel burn per 1,000 nm is in the top quartile of the fleet.
 * - `normal` — everything else.
 */
export const LANE_STATES = {
  normal: { label: 'Active route', tone: 'normal' },
  optimised: { label: 'Optimised route', tone: 'eco' },
  pressure: { label: 'Schedule pressure', tone: 'warning' },
  intensive: { label: 'High fuel intensity', tone: 'amber' },
}

/* -------------------------------------------------------------------------- */
/* Vessel status                                                               */
/* -------------------------------------------------------------------------- */
/**
 * A plan is an assignment, not a live position — nothing here claims to know
 * where a ship is right now. The status describes the *plan*, which is what
 * the project actually models.
 */
function vesselStatus(assignment, lane) {
  if (!assignment) return 'Unassigned'
  if (lane && assignment.voyage_days > lane.max_transit_days) return 'Over transit window'
  if (assignment.eca_switch_share > 0) return 'ECA transit'
  if (assignment.shore_power_pct > 0) return 'Shore power leg'
  return 'Assigned'
}

/* -------------------------------------------------------------------------- */
/* Main derivation                                                             */
/* -------------------------------------------------------------------------- */
/**
 * @param {object}   input
 * @param {object}   input.plan      the optimised plan, or null
 * @param {object}   input.baseline  the baseline deployment from /fleet
 * @param {Array}    input.lanes     registry lanes (distances, windows, basins)
 * @param {Array}    input.ports     registry ports (positions, country)
 */
export function buildNetworkIntel({ plan, baseline, lanes = EMPTY, ports = EMPTY } = {}) {
  const active = plan ?? baseline ?? null
  const source = plan ? 'optimised' : baseline ? 'baseline' : null

  if (!active) {
    return {
      source: null,
      ready: false,
      kpis: { vessels: 0, lanes: lanes.length, ports: ports.length, coverage: null },
      lanes: EMPTY,
      vessels: EMPTY,
      portStats: {},
      health: EMPTY,
      insights: EMPTY,
      fuelMix: {},
    }
  }

  const assignments = active.assignments ?? EMPTY
  const coverage = active.route_coverage ?? EMPTY
  const laneByName = Object.fromEntries(lanes.map((lane) => [lane.name, lane]))

  // Coverage is keyed by route name in the backend payload; normalise whether
  // it arrives as an array or an object so one shape reaches the UI.
  const coverageByName = Array.isArray(coverage)
    ? Object.fromEntries(coverage.map((row) => [row.route_name ?? row.name, row]))
    : coverage

  /* ---- per-lane roll-up ---------------------------------------------- */
  const byLane = new Map()
  assignments.forEach((a) => {
    const list = byLane.get(a.route_name) ?? []
    list.push(a)
    byLane.set(a.route_name, list)
  })

  // Baseline lookup, so an optimised plan can report a real delta per lane
  // rather than a fleet-wide average smeared across every route.
  const baselineByLane = new Map()
  if (plan && baseline) {
    ;(baseline.assignments ?? EMPTY).forEach((a) => {
      const row = baselineByLane.get(a.route_name) ?? { fuel: 0, co2: 0 }
      row.fuel += a.fuel_tons ?? 0
      row.co2 += a.co2_tons ?? 0
      baselineByLane.set(a.route_name, row)
    })
  }

  const laneRows = lanes.map((lane) => {
    const mine = byLane.get(lane.name) ?? EMPTY
    const cover = coverageByName?.[lane.name] ?? {}
    const fuelTons = mine.reduce((sum, a) => sum + (a.fuel_tons ?? 0), 0)
    const co2Tons = mine.reduce((sum, a) => sum + (a.co2_tons ?? 0), 0)
    const voyageDays = mean(mine.map((a) => a.voyage_days ?? 0))

    // Capacity used: the optimiser sizes each lane's demand in tons and knows
    // the deadweight it assigned. 20% means the lane is carrying five times
    // the tonnage it needs — slack, not a shortfall. `covered` is the boolean
    // that answers "is demand met".
    const demand = cover.demand_tons ?? 0
    const capacity = cover.capacity_tons ?? 0
    const utilisation = capacity > 0 ? Math.min(demand / capacity, 1) : null

    const base = baselineByLane.get(lane.name)
    const fuelDeltaPct = base?.fuel ? ((fuelTons - base.fuel) / base.fuel) * 100 : null
    const co2DeltaPct = base?.co2 ? ((co2Tons - base.co2) / base.co2) * 100 : null

    // Schedule pressure: what share of the contractual window the voyage uses.
    const schedulePressure =
      lane.max_transit_days > 0 && voyageDays > 0 ? voyageDays / lane.max_transit_days : null

    const fuelPerKnm = lane.distance_nm > 0 ? (fuelTons / lane.distance_nm) * 1000 : 0

    return {
      name: lane.name,
      origin: lane.origin,
      destination: lane.destination,
      originCode: lane.origin_code,
      destinationCode: lane.destination_code,
      via: lane.via,
      cargo: lane.cargo,
      distanceNm: lane.distance_nm,
      beaufort: lane.typical_beaufort ?? lane.weather_beaufort,
      shorePower: lane.shore_power_available,
      maxTransitDays: lane.max_transit_days,
      vessels: mine.length,
      avgSpeed: round(mean(mine.map((a) => a.speed_knots ?? 0)), 1),
      voyageDays: round(voyageDays, 2),
      fuelTons: round(fuelTons, 1),
      co2Tons: round(co2Tons, 1),
      fuelPerKnm: round(fuelPerKnm, 1),
      utilisation,
      covered: cover.covered ?? null,
      demandTons: demand,
      capacityTons: capacity,
      ecaFraction: mine.length ? mine[0].eca_fraction ?? 0 : 0,
      schedulePressure,
      fuelDeltaPct: fuelDeltaPct === null ? null : round(fuelDeltaPct, 1),
      co2DeltaPct: co2DeltaPct === null ? null : round(co2DeltaPct, 1),
      fuels: [...new Set(mine.map((a) => a.fuel_type))],
      state: 'normal',
    }
  })

  // Fuel intensity is only meaningful against the rest of the fleet, so the
  // threshold is the upper quartile of lanes that actually carry vessels.
  const intensities = laneRows
    .filter((row) => row.vessels > 0)
    .map((row) => row.fuelPerKnm)
    .sort((a, b) => a - b)
  const upperQuartile = intensities.length
    ? intensities[Math.floor(intensities.length * 0.75)]
    : Infinity

  laneRows.forEach((row) => {
    if (row.vessels === 0) return
    if (row.co2DeltaPct !== null && row.co2DeltaPct < -0.5) row.state = 'optimised'
    else if (row.schedulePressure !== null && row.schedulePressure >= 0.9) row.state = 'pressure'
    else if (row.fuelPerKnm >= upperQuartile && intensities.length > 3) row.state = 'intensive'
  })

  /* ---- per-vessel ------------------------------------------------------ */
  const vesselRows = assignments.map((a) => {
    const lane = laneByName[a.route_name]
    return {
      id: a.vessel_id,
      name: a.vessel_name,
      type: a.vessel_type,
      lane: a.route_name,
      route: lane ? `${lane.origin} → ${lane.destination}` : a.route_name,
      speed: a.speed_knots,
      fuel: a.fuel_type,
      distanceNm: a.distance_nm,
      voyageDays: a.voyage_days,
      fuelTons: a.fuel_tons,
      co2Tons: a.co2_tons,
      ecaShare: a.eca_switch_share ?? 0,
      shorePowerPct: a.shore_power_pct ?? 0,
      ciiRating: a.cii?.rating ?? null,
      status: vesselStatus(a, lane),
    }
  })

  /* ---- per-port -------------------------------------------------------- */
  // What a port genuinely knows in this project: which lanes touch it, how
  // many planned voyages call there, and the bunker volume those voyages
  // burn. Arrivals, departures and turnaround are not modelled — see
  // UNAVAILABLE.
  const portStats = {}
  laneRows.forEach((row) => {
    ;[
      [row.origin, row.originCode],
      [row.destination, row.destinationCode],
    ].forEach(([name, code]) => {
      if (!name) return
      const entry = (portStats[name] ??= {
        name,
        code,
        lanes: [],
        vessels: 0,
        fuelTons: 0,
        co2Tons: 0,
        shorePowerLanes: 0,
      })
      entry.lanes.push(row.name)
      entry.vessels += row.vessels
      entry.fuelTons += row.fuelTons
      entry.co2Tons += row.co2Tons
      if (row.shorePower) entry.shorePowerLanes += 1
    })
  })
  Object.values(portStats).forEach((entry) => {
    entry.fuelTons = round(entry.fuelTons, 1)
    entry.co2Tons = round(entry.co2Tons, 1)
    entry.laneCount = entry.lanes.length
  })

  /* ---- network health -------------------------------------------------- */
  // Four measures, each with a source. No composite "health score", because a
  // single number blended from four different units means nothing.
  const withVessels = laneRows.filter((row) => row.vessels > 0)
  const covered = withVessels.filter((row) => row.covered).length
  const onSchedule = withVessels.filter(
    (row) => row.schedulePressure !== null && row.schedulePressure <= 1,
  ).length

  const ecaAssignments = assignments.filter((a) => (a.eca_fraction ?? 0) > 0)
  const ecaCompliant = ecaAssignments.filter(
    (a) => a.eca_compliant_fuel || (a.eca_switch_share ?? 0) > 0,
  ).length

  const planFuel = active.objectives?.fuel_consumption_tons ?? null
  const baseFuel = baseline?.objectives?.fuel_consumption_tons ?? null
  const fuelEfficiency =
    plan && planFuel !== null && baseFuel ? Math.max(0, 1 - planFuel / baseFuel) : null

  const health = [
    {
      label: 'Demand coverage',
      value: withVessels.length ? covered / withVessels.length : null,
      detail: `${covered} of ${withVessels.length} lanes carry enough deadweight for their demand`,
      source: 'route_coverage.covered',
    },
    {
      label: 'Schedule adherence',
      value: withVessels.length ? onSchedule / withVessels.length : null,
      detail: `${onSchedule} of ${withVessels.length} voyages fit their transit window`,
      source: 'voyage_days vs lane.max_transit_days',
    },
    {
      label: 'ECA compliance',
      value: ecaAssignments.length ? ecaCompliant / ecaAssignments.length : null,
      detail: ecaAssignments.length
        ? `${ecaCompliant} of ${ecaAssignments.length} ECA voyages on compliant fuel`
        : 'No voyage on this plan enters an emission control area',
      source: 'eca_compliant_fuel / eca_switch_share',
    },
    {
      label: 'Fuel saving vs baseline',
      value: fuelEfficiency,
      detail: plan
        ? `${round((baseFuel - planFuel) / 1, 0).toLocaleString()} t less than the baseline deployment`
        : 'Run an optimisation to measure this',
      source: 'plan vs baseline objectives',
    },
  ]

  /* ---- insights -------------------------------------------------------- */
  const insights = []
  const optimisable = laneRows.filter((row) => row.state === 'optimised')
  const pressured = laneRows.filter((row) => row.state === 'pressure')
  const intensive = laneRows.filter((row) => row.state === 'intensive')

  if (plan && optimisable.length) {
    const best = [...optimisable].sort((a, b) => a.co2DeltaPct - b.co2DeltaPct)[0]
    insights.push({
      tone: 'eco',
      key: 'best-lane',
      text: `${best.origin}–${best.destination} carries the largest CO₂ reduction in this plan, at ${Math.abs(best.co2DeltaPct).toFixed(1)}%.`,
    })
    insights.push({
      tone: 'eco',
      key: 'optimised-count',
      text: `${optimisable.length} of ${withVessels.length} active lanes improved on the baseline.`,
    })
  } else {
    insights.push({
      tone: 'info',
      key: 'no-plan',
      text: 'Showing the baseline deployment. Run an optimisation to see where fuel and CO₂ can be taken out.',
    })
  }

  // Fuel intensity by fuel type — real, from the assignments on this plan.
  const byFuel = {}
  assignments.forEach((a) => {
    const entry = (byFuel[a.fuel_type] ??= { fuel: 0, nm: 0, vessels: 0 })
    entry.fuel += a.fuel_tons ?? 0
    entry.nm += a.distance_nm ?? 0
    entry.vessels += 1
  })
  const fuelRanked = Object.entries(byFuel)
    .filter(([, v]) => v.nm > 0)
    .map(([name, v]) => ({ name, perKnm: (v.fuel / v.nm) * 1000, vessels: v.vessels }))
    .sort((a, b) => a.perKnm - b.perKnm)
  if (fuelRanked.length > 1) {
    insights.push({
      tone: 'info',
      key: 'fuel-intensity',
      text: `${fuelRanked[0].name} shows the lowest fuel intensity on this plan, at ${fuelRanked[0].perKnm.toFixed(1)} t per 1,000 nm across ${fuelRanked[0].vessels} vessel${fuelRanked[0].vessels === 1 ? '' : 's'}.`,
    })
  }

  if (pressured.length) {
    insights.push({
      tone: 'warning',
      key: 'pressure',
      text: `${pressured.length} lane${pressured.length === 1 ? ' uses' : 's use'} 90% or more of the contractual transit window — ${pressured[0].origin}–${pressured[0].destination} has the least slack.`,
    })
  }
  if (intensive.length) {
    insights.push({
      tone: 'amber',
      key: 'intensity',
      text: `${intensive.length} lane${intensive.length === 1 ? ' burns' : 's burn'} in the top quartile per 1,000 nm — candidates for a speed or fuel change.`,
    })
  }
  const uncovered = withVessels.filter((row) => row.covered === false)
  if (uncovered.length) {
    insights.push({
      tone: 'warning',
      key: 'uncovered',
      text: `${uncovered.length} lane${uncovered.length === 1 ? ' carries' : 's carry'} less deadweight than their demand.`,
    })
  }

  /* ---- KPIs ------------------------------------------------------------ */
  return {
    source,
    ready: true,
    feasible: active.feasible ?? null,
    kpis: {
      vessels: assignments.length,
      lanes: withVessels.length,
      totalLanes: lanes.length,
      ports: Object.keys(portStats).length,
      coverage: withVessels.length ? covered / withVessels.length : null,
    },
    objectives: active.objectives ?? null,
    baselineObjectives: baseline?.objectives ?? null,
    lanes: laneRows,
    vessels: vesselRows,
    portStats,
    health,
    insights,
    fuelMix: active.fuel_mix ?? {},
    fuelRanked,
    averageSpeed: active.average_speed_knots ?? null,
  }
}

/**
 * Where along its lane to draw a vessel.
 *
 * Spread deterministically by vessel id rather than animated or randomised:
 * the plan says which ship sails which lane, not where it is at this instant,
 * and a marker that drifts would be claiming a position the data does not
 * have. Deterministic means the same plan always draws the same picture.
 */
export function vesselProgress(vessel, indexWithinLane, laneVesselCount) {
  const slots = Math.max(laneVesselCount, 1)
  return (indexWithinLane + 0.5) / slots
}

export default buildNetworkIntel
