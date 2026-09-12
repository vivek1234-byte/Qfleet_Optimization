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
  // The readouts React renders from. Set ONLY on the publish cadence below.
  //
  // This used to be a bare tick counter, with the readouts read straight off
  // `engineRef.current` at render time. That coupled every number on the page
  // to *when* React happened to render: the RAF loop mutates the ref sixty
  // times a second, so a render triggered by anything at all — a zoom click,
  // a pan, a hover — read a fresher, later value than the last publish. The
  // voyage-cost figure visibly jumped every time the map was zoomed, because
  // zooming re-rendered the page and the page re-read a moving number.
  //
  // Now the loop copies the engine state into React state four times a
  // second, and that copy is what every readout uses. A render caused by the
  // viewport shows exactly the same figures as the render before it. Only the
  // clock advancing — or a decision, a scrub, a reset — produces a new copy.
  const [published, setPublished] = useState(() => ({
    hours: 0,
    realSeconds: 0,
    snapshots: EMPTY,
    byId: new Map(),
    events: EMPTY,
    tally: { atSea: 0, inPort: 0, held: 0, total: 0 },
    next: null,
  }))

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

  /** Copy the engine's current readouts into React state. */
  const publish = useCallback(() => {
    const e = engineRef.current
    setPublished({
      hours: e.hours,
      realSeconds: e.realSeconds,
      snapshots: e.snapshots,
      byId: e.byId,
      events: e.events,
      tally: e.tally,
      next: e.next,
    })
  }, [])

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
    publish()
  }, [decisions, fleet, recompute, publish])

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
        publish()
      }
    }

    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [recompute, publish])

  /* ---- controls --------------------------------------------------------- */
  const jumpTo = useCallback(
    (hours) => {
      const target = Math.max(0, hours)
      // Backwards needs a replay from zero; forwards can continue cheaply.
      recompute(target, { fromScratch: target < engineRef.current.hours })
      publish()
    },
    [recompute, publish],
  )

  const stepBy = useCallback((hours) => jumpTo(engineRef.current.hours + hours), [jumpTo])

  const reset = useCallback(() => {
    stateRef.current = null
    engineRef.current.hours = 0
    engineRef.current.realSeconds = 0
    // Dropping the decisions is the reset — the world is a function of them.
    setDecisions(createDecisions())
    recompute(0, { fromScratch: true })
    publish()
  }, [recompute, publish])

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
  // From the published copy, never the live ref — not even as a first-render
  // fallback. `engineRef` is still handed out for the 60 fps renderer, which
  // is the one consumer that *should* read the moving value: it draws
  // position, not numbers anyone reads.
  const engine = published
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
