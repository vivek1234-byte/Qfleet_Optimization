/**
 * The simulation kernel.
 *
 * One authoritative clock in simulated hours. Every vessel derives its state
 * from that clock and from a small set of *recorded decisions* — holds the
 * user applied, speed changes the user made. Nothing here uses wall-clock
 * time, frame counts or timers; `Simulator.jsx` owns the single
 * requestAnimationFrame loop and this module owns what the world looks like
 * at hour T.
 *
 * ## Why replay rather than integrate
 *
 * The obvious design is a mutable world advanced by a delta each frame. It
 * works until the user scrubs backwards, and then it cannot: an integrator
 * has thrown away the information needed to undo itself, so "− 1 h" either
 * lies or resets the voyage.
 *
 * So the world is a **pure function of (initial fleet, decisions, T)**, and
 * `simulateTo` replays from zero with a fixed internal step. Decisions are
 * stored as timestamped intervals — a hold is `{ from, to }` in simulated
 * hours, a speed change is `{ at, knots }` — which means the same T always
 * produces the same world, forwards, backwards or jumped to directly. Reset
 * is dropping the decisions.
 *
 * Replay costs a few thousand arithmetic steps for fourteen vessels, which is
 * nothing, and only happens when the user scrubs. The common case — the clock
 * ticking forward — advances incrementally from the last state.
 *
 * ## What is real
 *
 * Distance, speed, fuel and CO₂ come from the optimiser's own assignment for
 * each vessel (`shipsFromPlan`), apportioned by distance sailed, exactly as
 * `snapshotShip` already did. Changing a vessel's speed in the UI rescales
 * its burn by the cubic speed–power law the backend uses, so a speed change
 * moves fuel in the right direction by the right physics rather than by a
 * guess.
 */

/* -------------------------------------------------------------------------- */
/* States                                                                      */
/* -------------------------------------------------------------------------- */
export const STATE = {
  IN_PORT: 'IN_PORT',
  LOADING: 'LOADING',
  ALONGSIDE: 'ALONGSIDE',
  DEPARTING: 'DEPARTING',
  IN_TRANSIT: 'IN_TRANSIT',
  HELD: 'HELD',
  ARRIVED: 'ARRIVED',
  COMPLETED: 'COMPLETED',
}

export const STATE_META = {
  IN_PORT: { label: 'In port', icon: '⚓', tone: 'neutral' },
  LOADING: { label: 'Loading', icon: '⚓', tone: 'primary' },
  ALONGSIDE: { label: 'Alongside', icon: '⚓', tone: 'primary' },
  DEPARTING: { label: 'Departing', icon: '🚢', tone: 'primary' },
  IN_TRANSIT: { label: 'In transit', icon: '🚢', tone: 'eco' },
  HELD: { label: 'Held', icon: '⏸', tone: 'warning' },
  ARRIVED: { label: 'Arrived', icon: '✓', tone: 'eco' },
  COMPLETED: { label: 'Completed', icon: '✓', tone: 'neutral' },
}

/** Port phases, in order, as a share of the dwell. Arrival → departure. */
const DWELL_PHASES = [
  { state: STATE.ARRIVED, until: 0.08 },
  { state: STATE.ALONGSIDE, until: 0.5 },
  { state: STATE.LOADING, until: 0.9 },
  { state: STATE.DEPARTING, until: 1 },
]

export const DEFAULT_DWELL_HOURS = 18

/**
 * Replay granularity. Small enough that an arrival lands within three minutes
 * of its true time, large enough that a 30-day scrub is a few thousand steps.
 */
const STEP_HOURS = 0.05

/* -------------------------------------------------------------------------- */
/* Decisions                                                                   */
/* -------------------------------------------------------------------------- */
/**
 * Everything the user has done to the simulation, as data.
 *
 * `holds[id]` is a list of `{ from, to }` in simulated hours; `to === null`
 * means still held. `speeds[id]` is a list of `{ at, knots }`.
 *
 * **Every function below is pure.** None of them touches the object it is
 * given; each returns a new one, or the original unchanged when there is
 * nothing to record. That is not house style — React may invoke a state
 * updater twice with the same input, and a version of `holdVessel` that
 * pushed onto the existing array saw its own first push on the second call,
 * decided the vessel was already held, and returned the unchanged object, so
 * React bailed out of the render and the hold never reached the screen.
 */
export function createDecisions() {
  return { holds: {}, speeds: {}, dwellHours: DEFAULT_DWELL_HOURS }
}

export function isHeldAt(decisions, id, hours) {
  const list = decisions.holds[id]
  if (!list?.length) return false
  return list.some(({ from, to }) => hours >= from && (to === null || hours < to))
}

export function holdVessel(decisions, id, atHours) {
  if (isHeldAt(decisions, id, atHours)) return decisions
  // Scrubbing back past a hold and holding again would otherwise leave an
  // orphan interval in the future. A decision taken at T supersedes anything
  // recorded after T for that vessel.
  const list = (decisions.holds[id] ?? []).filter((h) => h.from <= atHours)
  return {
    ...decisions,
    holds: { ...decisions.holds, [id]: [...list, { from: atHours, to: null }] },
  }
}

export function releaseVessel(decisions, id, atHours) {
  const list = decisions.holds[id]
  if (!list?.length) return decisions
  const index = list.findIndex(({ from, to }) => atHours >= from && (to === null || atHours < to))
  if (index < 0) return decisions
  const next = list.slice()
  next[index] = { ...next[index], to: atHours }
  return { ...decisions, holds: { ...decisions.holds, [id]: next } }
}

export function setVesselSpeed(decisions, id, knots, atHours) {
  const list = decisions.speeds[id] ?? []
  // Dragging a slider fires dozens of changes on the same simulated hour, and
  // a scrub backwards can put a new order before an old one. Drop anything
  // recorded at or after this instant, then append — so the list stays sorted
  // and one drag leaves one decision behind, not two hundred.
  const kept = list.filter((s) => s.at < atHours)
  return { ...decisions, speeds: { ...decisions.speeds, [id]: [...kept, { at: atHours, knots }] } }
}

/** The commanded speed for a vessel at time T, or its plan speed if untouched. */
export function speedAt(decisions, ship, hours) {
  const list = decisions.speeds[ship.id]
  if (!list?.length) return ship.speedKnots
  let knots = ship.speedKnots
  for (const entry of list) {
    if (entry.at <= hours) knots = entry.knots
    else break
  }
  return knots
}

/* -------------------------------------------------------------------------- */
/* Per-vessel simulation                                                       */
/* -------------------------------------------------------------------------- */
function initialVessel(ship) {
  // `phaseHours` staggered the old cyclic animation so the fleet did not sail
  // as one convoy. It survives as a head start along the first leg, which
  // keeps the map looking like a working network from hour zero.
  const legHours = ship.distanceNm / Math.max(ship.speedKnots, 0.1)
  const head = legHours > 0 ? (ship.phaseHours ?? 0) % (legHours * 2) : 0
  const outbound = head <= legHours
  return {
    id: ship.id,
    state: STATE.IN_TRANSIT,
    inbound: !outbound,
    sailedNm: outbound
      ? ship.distanceNm * (head / Math.max(legHours, 0.001))
      : ship.distanceNm * (1 - (head - legHours) / Math.max(legHours, 0.001)),
    legsCompleted: 0,
    dwellRemaining: 0,
    dwellTotal: 0,
    dwellPort: null,
    sailingHours: 0,
    heldHours: 0,
    dwellHoursTotal: 0,
    arrivedAt: null,
    departsAt: null,
    // Running totals since the clock started, added to as the vessel moves.
    // These used to be derived from how far along the *current leg* the
    // vessel was, which meant every arrival reset them to zero and the fleet
    // figures sawtoothed as ships turned round at different times. Burn is
    // spent, not a position, so it accumulates.
    fuelTons: 0,
    co2Tons: 0,
    costUsd: 0,
  }
}

/**
 * Advance one vessel by `dt` simulated hours.
 *
 * Mutates `v` in place — it is a scratch object owned by the replay, never
 * shared with React — and pushes anything worth putting on the timeline into
 * `events`.
 */
function stepVessel(v, ship, decisions, dt, stepStart, nowHours, events) {
  // Decisions are evaluated at the START of the step and events stamped at
  // its end. Testing the hold at the end instead would discard the movement
  // of the step during which the hold was applied, leaving the vessel short
  // of where it was when the user pressed the button.
  const held = isHeldAt(decisions, ship.id, stepStart)

  if (held) {
    if (v.state !== STATE.HELD) {
      v.stateBeforeHold = v.state
      v.state = STATE.HELD
      events.push({
        at: nowHours,
        kind: 'held',
        shipId: ship.id,
        vessel: ship.vesselName,
        text: `Held at ${Math.round((v.sailedNm / Math.max(ship.distanceNm, 1)) * 100)}% of ${ship.laneName}`,
      })
    }
    v.heldHours += dt
    return
  }

  if (v.state === STATE.HELD) {
    // Resume exactly where it stopped — sailedNm was never touched while held.
    v.state = v.stateBeforeHold ?? STATE.IN_TRANSIT
    v.stateBeforeHold = null
    events.push({
      at: nowHours,
      kind: 'resumed',
      shipId: ship.id,
      vessel: ship.vesselName,
      text: `Resumed on ${ship.laneName}`,
    })
  }

  // --- alongside ---------------------------------------------------------
  if (v.dwellRemaining > 0) {
    v.dwellRemaining = Math.max(0, v.dwellRemaining - dt)
    v.dwellHoursTotal += dt
    const elapsed = 1 - v.dwellRemaining / Math.max(v.dwellTotal, 0.001)
    v.state = DWELL_PHASES.find((phase) => elapsed <= phase.until)?.state ?? STATE.DEPARTING
    if (v.dwellRemaining === 0) {
      v.state = STATE.IN_TRANSIT
      v.inbound = !v.inbound
      v.sailedNm = v.inbound ? ship.distanceNm : 0
      v.arrivedAt = null
      events.push({
        at: nowHours,
        kind: 'departed',
        shipId: ship.id,
        vessel: ship.vesselName,
        port: v.dwellPort,
        text: `Departed ${v.dwellPort}`,
      })
      v.dwellPort = null
    }
    return
  }

  // --- at sea ------------------------------------------------------------
  const knots = Math.max(speedAt(decisions, ship, stepStart), 0)
  if (knots <= 0) {
    // Commanded to zero: stationary, but not "held" — the distinction matters
    // because a hold is a user decision the timeline records.
    v.state = STATE.IN_TRANSIT
    return
  }

  v.state = STATE.IN_TRANSIT
  v.sailingHours += dt
  const travelled = knots * dt
  v.sailedNm = v.inbound ? v.sailedNm - travelled : v.sailedNm + travelled

  // Bank what this step cost, at the speed actually sailed during it.
  //
  // Two bugs die here. Deriving the total from leg progress reset it on every
  // turnaround; and multiplying the whole accumulated voyage by the *current*
  // speed factor re-priced fuel already burnt whenever the user moved the
  // speed dial, so a nudge at hour 80 changed what hour 3 had cost. Charging
  // each step as it happens leaves the past alone and only ever adds.
  //
  // Power goes as v³ and time as 1/v, so fuel per mile goes as v² — the same
  // law `estimateVoyage` and the backend's `fleet_problem` use.
  if (travelled > 0 && ship.distanceNm > 0) {
    const ratio = ship.speedKnots > 0 ? knots / ship.speedKnots : 1
    const share = (travelled / ship.distanceNm) * ratio * ratio
    v.fuelTons += (ship.fuelTons ?? 0) * share
    v.co2Tons += (ship.co2Tons ?? 0) * share
    v.costUsd += (ship.costUsd ?? 0) * share
  }

  // Epsilon, because `sailedNm` is six hundred accumulated additions and
  // lands on 599.9999999999 as readily as on 600. A vessel a millimetre off
  // the berth has arrived; letting float luck decide would make arrival
  // non-deterministic across different step counts.
  const BERTH_EPSILON_NM = 1e-6
  const arrivedOutbound = !v.inbound && v.sailedNm >= ship.distanceNm - BERTH_EPSILON_NM
  const arrivedInbound = v.inbound && v.sailedNm <= BERTH_EPSILON_NM
  if (arrivedOutbound || arrivedInbound) {
    v.sailedNm = arrivedOutbound ? ship.distanceNm : 0
    v.legsCompleted += 1
    v.dwellTotal = decisions.dwellHours
    v.dwellRemaining = decisions.dwellHours
    v.dwellPort = arrivedOutbound ? ship.destinationName : ship.originName
    v.state = STATE.ARRIVED
    v.arrivedAt = nowHours
    v.departsAt = nowHours + decisions.dwellHours
    events.push({
      at: nowHours,
      kind: 'arrived',
      shipId: ship.id,
      vessel: ship.vesselName,
      port: v.dwellPort,
      text: `Arrived ${v.dwellPort}`,
    })
    // Dwell set to zero: turn round here and now. Leaving it to the dwell
    // branch would not work — that branch only runs while `dwellRemaining > 0`,
    // so the vessel would sail straight past the berth and re-arrive on every
    // step, logging an arrival each time.
    if (v.dwellRemaining <= 0) {
      v.state = STATE.IN_TRANSIT
      v.inbound = !v.inbound
      v.sailedNm = v.inbound ? ship.distanceNm : 0
      v.arrivedAt = null
      v.dwellPort = null
    }
  }
}

/* -------------------------------------------------------------------------- */
/* Replay                                                                      */
/* -------------------------------------------------------------------------- */
/**
 * The world at `targetHours`.
 *
 * `from` lets the caller continue an existing state forward cheaply; omit it
 * (or pass a target earlier than the state's own clock) and the whole thing
 * replays from zero, which is what makes scrubbing backwards exact.
 */
export function simulateTo(ships, decisions, targetHours, from = null) {
  const canContinue = from && from.hours <= targetHours + 1e-9
  const vessels = canContinue
    ? from.vessels.map((v) => ({ ...v }))
    : ships.map((ship) => initialVessel(ship))
  const events = canContinue ? from.events.slice() : []
  let hours = canContinue ? from.hours : 0

  const byId = new Map(ships.map((ship) => [ship.id, ship]))
  let guard = 0
  // Step boundaries are computed from an integer index against absolute zero,
  // never accumulated. Accumulating 240 additions of 0.05 lands on 5.99999…
  // where 120 lands on 6.0, and a hold recorded at hour 6 would then be missed
  // by one step on the longer replay — the vessel would creep 0.7 nm forward
  // every time the history was replayed rather than continued.
  let index = Math.round(hours / STEP_HOURS)
  while (hours < targetHours - 1e-9) {
    const stepStart = hours
    index += 1
    hours = Math.min(targetHours, index * STEP_HOURS)
    const dt = hours - stepStart
    for (const v of vessels) {
      const ship = byId.get(v.id)
      if (ship) stepVessel(v, ship, decisions, dt, stepStart, hours, events)
    }
    // 20,000 steps is 1,000 simulated hours at the replay granularity; past
    // that the user has scrubbed further than the UI can offer and something
    // is wrong. Stop rather than lock the tab up.
    if ((guard += 1) > 40000) break
  }
  // Accumulated dt drifts in the last bits; the target is authoritative.
  hours = targetHours

  // Settle. A decision taken at exactly T — the user pressing Hold now — is
  // true at T but is never the *start* of a step, so the replay would not act
  // on it until the clock moved past T, and while paused it never would. A
  // zero-length step at T applies it without moving anything.
  for (const v of vessels) {
    const ship = byId.get(v.id)
    if (ship) stepVessel(v, ship, decisions, 0, targetHours, targetHours, events)
  }

  // Timeline stays bounded — the panel shows the most recent handful and the
  // array is otherwise pure memory pressure on a long run.
  const trimmed = events.length > 400 ? events.slice(events.length - 400) : events
  return { hours, vessels, events: trimmed }
}

/* -------------------------------------------------------------------------- */
/* Readouts                                                                    */
/* -------------------------------------------------------------------------- */
/**
 * What one vessel has spent, and how far along its current leg it is.
 *
 * `fraction` is a position — where the ship is on this leg, 0 to 1 — and
 * resets each time it turns round, which is what the progress bar wants.
 * Fuel, CO₂ and cost are not positions: they are banked step by step in
 * `stepVessel` and only ever grow. Reading them off `fraction`, as this used
 * to, made every arrival look like the fleet had un-burnt its fuel.
 */
export function vesselBurn(ship, v) {
  const sailedNm = v.inbound ? ship.distanceNm - v.sailedNm : v.sailedNm
  const fraction = ship.distanceNm > 0 ? Math.min(sailedNm / ship.distanceNm, 1) : 0
  return {
    fraction,
    fuelTons: v.fuelTons ?? 0,
    co2Tons: v.co2Tons ?? 0,
    costUsd: v.costUsd ?? 0,
  }
}

/**
 * What one voyage on this lane costs and emits — a pure function of the
 * inputs, never of the clock.
 *
 * `x = calculate(currentData)`: the plan's own figures for this assignment
 * (`fuel_tons`, `co2_tons`, `cost_usd` from the optimiser, or `estimateVoyage`
 * for an un-optimised vessel) re-priced for the speed the operator has
 * ordered, using the same v² fuel-per-mile law as `stepVessel`,
 * `estimateVoyage` and the backend's `_voyage_terms`. Nothing is accumulated
 * and nothing is read from the vessel's running state, so calling this at
 * hour 0 and at hour 500 returns the same figures unless a genuine input —
 * the plan, the lane, the fuel, or the ordered speed — has changed.
 *
 * Deliberately separate from `vesselBurn()`, which reports what has been
 * *spent so far* and grows with simulated time by definition. Intensity
 * comparisons and the "Voyage cost" readout want this one; "fuel burnt" and
 * "CO₂e emitted" want the accumulator.
 */
export function voyagePlan(ship, commandedKnots) {
  const plan = ship.speedKnots ?? 0
  const ordered = commandedKnots ?? plan
  // Power goes as v³ and time as 1/v, so per-mile burn goes as v².
  const factor = plan > 0 && ordered > 0 ? (ordered / plan) ** 2 : 1
  return {
    fuelTons: (ship.fuelTons ?? 0) * factor,
    co2Tons: (ship.co2Tons ?? 0) * factor,
    costUsd: (ship.costUsd ?? 0) * factor,
    speedFactor: factor,
  }
}

/** Just the cost half of {@link voyagePlan}. */
export function voyageCost(ship, commandedKnots) {
  return voyagePlan(ship, commandedKnots).costUsd
}

/**
 * Fuel, CO₂ and cost per nautical mile for a fleet, from its plan.
 *
 * The only fair way to compare two fleets of different sizes — the optimised
 * plan puts twenty vessels to sea where the registry baseline sails fourteen,
 * so totals flatter the smaller fleet and per-vessel averages flatter whoever
 * sails shorter lanes. Tonnes per mile is what neither side can game, and it
 * is the basis the IMO's own carbon-intensity measures use.
 *
 * Planned rather than simulated on purpose: a fleet's intensity is a property
 * of the assignment, so it is known at hour zero and does not wobble with
 * which particular vessels happen to be alongside at this minute.
 */
export function fleetIntensity(ships, speedFor = null) {
  let fuel = 0
  let co2 = 0
  let cost = 0
  let nm = 0
  for (const ship of ships) {
    const plan = voyagePlan(ship, speedFor ? speedFor(ship) : ship.speedKnots)
    fuel += plan.fuelTons
    co2 += plan.co2Tons
    cost += plan.costUsd
    nm += ship.distanceNm ?? 0
  }
  if (!(nm > 0)) return null
  return { fuelPerNm: fuel / nm, co2PerNm: co2 / nm, costPerNm: cost / nm, nm }
}

/** Everything the fleet panel and the map need for one vessel. */
export function vesselSnapshot(ship, v, decisions, hours) {
  const burn = vesselBurn(ship, v)
  const knots = speedAt(decisions, ship, hours)
  const plan = voyagePlan(ship, knots)
  const remainingNm = v.inbound ? v.sailedNm : ship.distanceNm - v.sailedNm
  const movingState = v.state === STATE.IN_TRANSIT && knots > 0
  return {
    id: ship.id,
    vesselName: ship.vesselName,
    vesselType: ship.vesselType,
    fuelType: ship.fuelType,
    laneName: ship.laneName,
    originName: ship.originName,
    destinationName: ship.destinationName,
    shorePowerPct: ship.shorePowerPct ?? 0,
    state: v.state,
    inbound: v.inbound,
    heading: v.inbound ? ship.originName : ship.destinationName,
    speedKnots: v.state === STATE.IN_TRANSIT ? knots : 0,
    commandedKnots: knots,
    planSpeedKnots: ship.speedKnots,
    progress: ship.distanceNm > 0 ? burn.fraction : 0,
    sailedNm: v.inbound ? ship.distanceNm - v.sailedNm : v.sailedNm,
    positionNm: v.sailedNm,
    remainingNm,
    distanceNm: ship.distanceNm,
    etaHours: movingState && knots > 0 ? remainingNm / knots : null,
    dwellRemaining: v.dwellRemaining,
    dwellTotal: v.dwellTotal,
    dwellPort: v.dwellPort,
    dwellProgress: v.dwellTotal > 0 ? 1 - v.dwellRemaining / v.dwellTotal : 0,
    arrivedAt: v.arrivedAt,
    departsAt: v.departsAt,
    legsCompleted: v.legsCompleted,
    held: v.state === STATE.HELD,
    // Spent so far — running totals, grow with the clock.
    fuelTons: burn.fuelTons,
    co2Tons: burn.co2Tons,
    costBurntUsd: burn.costUsd,
    // Planned for the whole voyage at the speed actually ordered — derived
    // from the inputs, independent of the clock.
    planFuelTons: plan.fuelTons,
    planCo2Tons: plan.co2Tons,
    voyageCostUsd: plan.costUsd,
    cii: ship.cii,
    ecaFraction: ship.ecaFraction,
  }
}

/**
 * The next thing that will happen, and when.
 *
 * Computed from the current state rather than by simulating ahead: a moving
 * vessel's arrival is distance over speed, and a berthed one's departure is
 * its remaining dwell. Held vessels have no next event by definition — that
 * is what being held means.
 */
export function nextEvent(ships, state, decisions) {
  let best = null
  const byId = new Map(ships.map((ship) => [ship.id, ship]))
  for (const v of state.vessels) {
    const ship = byId.get(v.id)
    if (!ship) continue
    if (v.state === STATE.HELD) continue

    if (v.dwellRemaining > 0) {
      const inHours = v.dwellRemaining
      if (!best || inHours < best.inHours) {
        best = {
          inHours,
          at: state.hours + inHours,
          kind: 'departure',
          shipId: ship.id,
          text: `${ship.vesselName} departs ${v.dwellPort}`,
        }
      }
      continue
    }

    const knots = speedAt(decisions, ship, state.hours)
    if (knots <= 0) continue
    const remainingNm = v.inbound ? v.sailedNm : ship.distanceNm - v.sailedNm
    const inHours = remainingNm / knots
    if (inHours >= 0 && (!best || inHours < best.inHours)) {
      best = {
        inHours,
        at: state.hours + inHours,
        kind: 'arrival',
        shipId: ship.id,
        text: `${ship.vesselName} arrives ${v.inbound ? ship.originName : ship.destinationName}`,
      }
    }
  }
  return best
}

/** How many vessels are at sea, alongside, or held — for the status bar. */
export function fleetTally(state) {
  const tally = { atSea: 0, inPort: 0, held: 0, total: state.vessels.length }
  for (const v of state.vessels) {
    if (v.state === STATE.HELD) tally.held += 1
    else if (v.dwellRemaining > 0) tally.inPort += 1
    else tally.atSea += 1
  }
  return tally
}

/* -------------------------------------------------------------------------- */
/* Clock presets                                                               */
/* -------------------------------------------------------------------------- */
/**
 * Simulated hours per real second.
 *
 * These control the clock and nothing else. A voyage that takes 120 simulated
 * hours takes 120 real seconds at 1 h/s and 20 at 6 h/s — the voyage itself is
 * unchanged, because position is a function of simulated time.
 */
export const SIM_SPEEDS = [
  { id: 'realtime', label: 'Real time', hoursPerSecond: 1 / 3600, note: '1 real second = 1 second' },
  { id: 'q', label: '0.25 h/s', hoursPerSecond: 0.25, note: '1 real second = 15 minutes' },
  { id: 'h', label: '0.5 h/s', hoursPerSecond: 0.5, note: '1 real second = 30 minutes' },
  { id: 'x1', label: '1 h/s', hoursPerSecond: 1, note: '1 real second = 1 hour' },
  // 1.5 h/s exists so the primary 1× / 2× / 6× pills are honest multiples of
  // a 0.25 h/s base. Without it, "6×" would have to point at 1 h/s, which is
  // four times the base, not six.
  { id: 'x1_5', label: '1.5 h/s', hoursPerSecond: 1.5, note: '1 real second = 90 minutes' },
  { id: 'x2', label: '2 h/s', hoursPerSecond: 2, note: '1 real second = 2 hours' },
  { id: 'x6', label: '6 h/s', hoursPerSecond: 6, note: '1 real second = 6 hours' },
  { id: 'x12', label: '12 h/s', hoursPerSecond: 12, note: '1 real second = 12 hours' },
  { id: 'day', label: '1 d/s', hoursPerSecond: 24, note: '1 real second = 1 day' },
]

export const STEP_PRESETS = [
  { id: 'h1', label: '+1 h', hours: 1 },
  { id: 'h6', label: '+6 h', hours: 6 },
  { id: 'd1', label: '+1 d', hours: 24 },
]

export default simulateTo
