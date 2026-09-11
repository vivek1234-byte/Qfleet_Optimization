/**
 * The simulation's single clock.
 *
 * One `requestAnimationFrame` loop for the whole page. It does exactly two
 * things: advance the simulated clock by `realSeconds × hoursPerSecond`, and
 * ask `simEngine` what the world looks like at that hour. There is no timer
 * per vessel, no timer per panel, and no second clock anywhere — everything
 * on screen reads from the state this hook publishes.
 *
 * Two clocks live here, kept deliberately apart:
 *
 * - `engineRef.current` — simulated time and per-vessel snapshots, mutated in
 *   place and read at 60 fps by the map renderer without going through React.
 * - React state (`tick`) — published four times a second for the panels, so
 *   fourteen vessels do not cause fourteen re-renders a frame.
 *
 * Pausing stops the first, which stops everything downstream by construction:
 * positions, fuel, CO₂ and ETAs are all functions of simulated time, so if it
 * does not advance, none of them can.
 *
 * **On the split comparison.** Both fleets are simulated by one call, as one
 * vessel list, so "one clock for both panes" is not a discipline the page has
 * to maintain — there is only one clock to share. `extraShips` are drawn and
 * snapshotted but left out of the status bar, the timeline and the next-event
 * prediction, which are about the fleet the operator is actually flying.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  createDecisions,
  fleetTally,
  holdVessel,
  isHeldAt,
  nextEvent as findNextEvent,
  releaseVessel,
  setVesselSpeed,
  simulateTo,
  vesselSnapshot,
} from '../lib/simEngine'

/** How often React is told about the new world. 4 Hz is faster than reading. */
const PUBLISH_MS = 250

/** Largest real-time delta honoured in one frame — a backgrounded tab must not
 *  return and leap a week. */
const MAX_FRAME_SECONDS = 0.25

const EMPTY = []

export function useSimulation(
  ships,
  { hoursPerSecond = 1, running = true, extraShips = EMPTY } = {},
) {
  const [decisions, setDecisions] = useState(createDecisions)
  const [, setTick] = useState(0)

  // Everything the renderer reads at 60 fps, mutated in place.
  const engineRef = useRef({
    hours: 0,
    byId: new Map(),
    snapshots: EMPTY,
    events: EMPTY,
    tally: { atSea: 0, inPort: 0, held: 0, total: 0 },
    next: null,
    realSeconds: 0,
  })
  const stateRef = useRef(null)

  const fleet = useMemo(
    () => (extraShips.length ? [...ships, ...extraShips] : ships),
    [ships, extraShips],
  )
  const primaryIds = useMemo(() => new Set(ships.map((s) => s.id)), [ships])

  // Live props for the loop, so changing the speed does not tear the loop down.
  const liveRef = useRef(null)
  liveRef.current = { hoursPerSecond, running, fleet, decisions, primaryIds }

  /** Recompute the world at `target` and republish it into `engineRef`. */
  const recompute = useCallback((target, { fromScratch = false } = {}) => {
    const { fleet: list, decisions: d, primaryIds: ids } = liveRef.current
    const hours = Math.max(0, target)
    if (!list.length) {
      engineRef.current = { ...engineRef.current, hours, byId: new Map(), snapshots: EMPTY }
      return
    }

    const previous = fromScratch ? null : stateRef.current
    const next = simulateTo(list, d, hours, previous)
    stateRef.current = next

    const shipById = new Map(list.map((s) => [s.id, s]))
    const byId = new Map()
    const snapshots = []
    next.vessels.forEach((v) => {
      const ship = shipById.get(v.id)
      if (!ship) return
      const snapshot = vesselSnapshot(ship, v, d, next.hours)
      byId.set(v.id, snapshot)
      snapshots.push(snapshot)
    })

    // Status bar, timeline and next-event are about the primary fleet only.
    const primaryShips = list.filter((s) => ids.has(s.id))
    const primaryState = {
      hours: next.hours,
      vessels: next.vessels.filter((v) => ids.has(v.id)),
      events: next.events,
    }

    engineRef.current = {
      ...engineRef.current,
      hours: next.hours,
      byId,
      snapshots,
      events: next.events.filter((e) => ids.has(e.shipId)),
      tally: fleetTally(primaryState),
      next: findNextEvent(primaryShips, primaryState, d),
    }
  }, [])

  // A decision changed (hold, release, speed, dwell), or the fleet was
  // replaced. Replay from zero so the change applies across the whole history
  // rather than being bolted onto the present.
  useEffect(() => {
    recompute(engineRef.current.hours, { fromScratch: true })
    setTick((t) => t + 1)
  }, [decisions, fleet, recompute])

  /* ---- the one loop ----------------------------------------------------- */
  useEffect(() => {
    let frame = 0
    let lastTs = 0
    let lastPublish = 0

    const step = (ts) => {
      frame = requestAnimationFrame(step)
      const { hoursPerSecond: hps, running: isRunning } = liveRef.current
      const dt = lastTs ? Math.min((ts - lastTs) / 1000, MAX_FRAME_SECONDS) : 0
      lastTs = ts

      if (isRunning && dt > 0) {
        engineRef.current.realSeconds += dt
        recompute(engineRef.current.hours + dt * hps)
      }
      // Publish on a fixed cadence whether or not the clock moved, so a step
      // or a scrub made while paused still reaches the panels.
      if (ts - lastPublish >= PUBLISH_MS) {
        lastPublish = ts
        setTick((t) => t + 1)
      }
    }

    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [recompute])

  /* ---- controls --------------------------------------------------------- */
  const jumpTo = useCallback(
    (hours) => {
      const target = Math.max(0, hours)
      // Backwards needs a replay from zero; forwards can continue cheaply.
      recompute(target, { fromScratch: target < engineRef.current.hours })
      setTick((t) => t + 1)
    },
    [recompute],
  )

  const stepBy = useCallback((hours) => jumpTo(engineRef.current.hours + hours), [jumpTo])

  const reset = useCallback(() => {
    stateRef.current = null
    engineRef.current.hours = 0
    engineRef.current.realSeconds = 0
    // Dropping the decisions is the reset — the world is a function of them.
    setDecisions(createDecisions())
    recompute(0, { fromScratch: true })
    setTick((t) => t + 1)
  }, [recompute])

  const hold = useCallback((id) => {
    setDecisions((d) => holdVessel(d, id, engineRef.current.hours))
  }, [])

  const release = useCallback((id) => {
    setDecisions((d) => releaseVessel(d, id, engineRef.current.hours))
  }, [])

  const toggleHold = useCallback(
    (id) => {
      if (isHeldAt(liveRef.current.decisions, id, engineRef.current.hours)) release(id)
      else hold(id)
    },
    [hold, release],
  )

  const holdAll = useCallback((ids) => {
    setDecisions((d) =>
      ids.reduce((acc, id) => holdVessel(acc, id, engineRef.current.hours), d),
    )
  }, [])

  const releaseAll = useCallback((ids) => {
    setDecisions((d) =>
      ids.reduce((acc, id) => releaseVessel(acc, id, engineRef.current.hours), d),
    )
  }, [])

  const setSpeed = useCallback((id, knots) => {
    setDecisions((d) => setVesselSpeed(d, id, knots, engineRef.current.hours))
  }, [])

  const setDwellHours = useCallback((hours) => {
    setDecisions((d) => ({ ...d, dwellHours: Math.max(0, hours) }))
  }, [])

  const jumpToNextEvent = useCallback(() => {
    const next = engineRef.current.next
    // Nudge past the event itself so the arrival has actually been recorded.
    if (next) jumpTo(next.at + 0.02)
  }, [jumpTo])

  /* ---- readouts --------------------------------------------------------- */
  // Read straight off the ref. It is mutated between renders on purpose; the
  // 4 Hz `setTick` above is what makes React look at it again.
  const engine = engineRef.current
  return {
    hours: engine.hours,
    realSeconds: engine.realSeconds,
    engineRef,
    snapshots: engine.snapshots,
    snapshotById: engine.byId,
    events: engine.events,
    nextEvent: engine.next,
    tally: engine.tally,
    decisions,
    // controls
    jumpTo,
    stepBy,
    reset,
    hold,
    release,
    toggleHold,
    holdAll,
    releaseAll,
    setSpeed,
    setDwellHours,
    jumpToNextEvent,
  }
}

export default useSimulation
