/**
 * The moving part of the simulator.
 *
 * Twenty vessels at 60 fps is 1,200 React renders a second, which is enough to
 * make the whole page stutter. So the animation loop writes SVG transforms
 * straight onto the DOM nodes through refs, and React is only asked to
 * re-render the side panel — at four frames a second, which is as fast as a
 * human can read a number anyway.
 */
import { memo, useCallback, useEffect, useLayoutEffect, useRef } from 'react'

import { useMapMetrics } from './WorldMap'
import { positionAt, trailPath } from '../data/geography'
import { fuelColor, vesselDeck, vesselShape } from '../lib/domain'

/** Hours a vessel spends alongside before turning round. */
export const PORT_TURNAROUND_HOURS = 18

/** On-screen height of a vessel marker, in CSS pixels, at any zoom. */
const MARKER_PX = 34

/**
 * Where a vessel is at a given point on the simulated clock.
 *
 * A voyage is modelled as a repeating cycle: sail out, work cargo, sail back,
 * work cargo. That keeps every vessel permanently visible, which is what you
 * want on a demo screen, and it is an honest picture of a liner service.
 */
export function voyageState(ship, hours) {
  const legHours = ship.distanceNm / Math.max(ship.speedKnots, 0.1)
  const cycle = 2 * (legHours + PORT_TURNAROUND_HOURS)
  const t = (((hours + ship.phaseHours) % cycle) + cycle) % cycle

  if (t < legHours) {
    const progress = t / legHours
    return { nm: ship.distanceNm * progress, progress, inbound: false, berthed: false, legHours, cycle, legTime: t }
  }
  if (t < legHours + PORT_TURNAROUND_HOURS) {
    return { nm: ship.distanceNm, progress: 1, inbound: false, berthed: true, legHours, cycle, legTime: legHours }
  }
  if (t < 2 * legHours + PORT_TURNAROUND_HOURS) {
    const legTime = t - legHours - PORT_TURNAROUND_HOURS
    const progress = legTime / legHours
    return {
      nm: ship.distanceNm * (1 - progress),
      progress,
      inbound: true,
      berthed: false,
      legHours,
      cycle,
      legTime,
    }
  }
  return { nm: 0, progress: 1, inbound: true, berthed: true, legHours, cycle, legTime: legHours }
}

/** Human snapshot of one vessel, for the side panel. */
export function snapshotShip(ship, hours) {
  const state = voyageState(ship, hours)
  const sailedNm = state.inbound ? ship.distanceNm * state.progress : state.nm
  // Fuel and CO2 come from the optimiser's own figures for this assignment,
  // apportioned by distance sailed. Nothing here is re-derived, so the ticker
  // and the plan table can never disagree.
  const fraction = ship.distanceNm > 0 ? sailedNm / ship.distanceNm : 0
  return {
    id: ship.id,
    vesselName: ship.vesselName,
    vesselType: ship.vesselType,
    fuelType: ship.fuelType,
    laneName: ship.laneName,
    speedKnots: ship.speedKnots,
    shorePowerPct: ship.shorePowerPct,
    ecaFraction: ship.ecaFraction ?? 0,
    cii: ship.cii ?? null,
    berthed: state.berthed,
    inbound: state.inbound,
    progressPct: state.progress * 100,
    sailedNm,
    remainingNm: Math.max(ship.distanceNm - sailedNm, 0),
    etaHours: state.berthed ? 0 : (ship.distanceNm - sailedNm) / Math.max(ship.speedKnots, 0.1),
    fuelTons: ship.fuelTons * fraction,
    co2Tons: ship.co2Tons * fraction,
    costUsd: ship.costUsd * fraction,
    port: state.berthed ? (state.inbound ? ship.originName : ship.destinationName) : null,
  }
}

/* -------------------------------------------------------------------------- */
/* Marker                                                                      */
/* -------------------------------------------------------------------------- */
const ShipMarker = memo(
  function ShipMarker({ ship, selected, dimmed, onSelect, registerRef }) {
    const color = fuelColor(ship.fuelType)
    return (
      <g className="ship-marker" opacity={dimmed ? 0.22 : 1}>
        <path
          ref={(el) => registerRef(ship.id, 'trail', el)}
          fill="none"
          stroke={color}
          strokeWidth={0.22}
          strokeOpacity={0.55}
          strokeLinecap="round"
        />
        <g ref={(el) => registerRef(ship.id, 'body', el)}>
          <g
            ref={(el) => registerRef(ship.id, 'hull', el)}
            onClick={(event) => {
              event.stopPropagation()
              onSelect(ship.id)
            }}
            filter={selected ? 'url(#ship-glow)' : undefined}
          >
            {/* Invisible disc so the vessel is clickable at any zoom. */}
            <circle r={10} fill="transparent" />
            {selected && (
              <circle r={17} fill="none" stroke="#fbbf24" strokeWidth={1.6} strokeDasharray="5 4" />
            )}
            {/* A dark shadow under the hull separates the marker from a lane
                line of the same colour running underneath it. */}
            <path
              d={vesselShape(ship.vesselType)}
              fill="#020a14"
              fillOpacity={0.55}
              transform="translate(0.6 0.9) scale(1.12)"
            />
            <path
              className="ship-hull"
              d={vesselShape(ship.vesselType)}
              fill={color}
              stroke="#f8fbff"
              strokeWidth={0.7}
              strokeOpacity={0.85}
              strokeLinejoin="round"
            />
            {vesselDeck(ship.vesselType).map((d, i) => (
              <rect
                key={i}
                x={d.x}
                y={d.y}
                width={d.w}
                height={d.h}
                rx={d.r}
                fill="#04101c"
                fillOpacity={0.28}
              />
            ))}
            {/* Bow wave, so heading is readable without reading the hull. */}
            <path
              d="M-2.6 -9.5 L0 -14.6 L2.6 -9.5"
              fill="none"
              stroke="#ffffff"
              strokeWidth={1}
              strokeOpacity={0.75}
              strokeLinecap="round"
            />
            <title>
              {ship.vesselName} · {ship.vesselType} · {ship.fuelType} · {ship.speedKnots} kn ·{' '}
              {ship.laneName}
            </title>
          </g>
        </g>
        <text
          ref={(el) => registerRef(ship.id, 'label', el)}
          textAnchor="middle"
          fill="#e8f3ff"
          stroke="rgb(var(--map-ocean))"
          paintOrder="stroke"
          style={{ pointerEvents: 'none', fontWeight: 600 }}
        />
      </g>
    )
  },
  (a, b) =>
    a.ship === b.ship && a.selected === b.selected && a.dimmed === b.dimmed && a.onSelect === b.onSelect,
)

/* -------------------------------------------------------------------------- */
/* Layer                                                                       */
/* -------------------------------------------------------------------------- */
export default function ShipLayer({
  ships,
  geometries,
  clockRef,
  running,
  timeScale,
  selectedId,
  dimmedIds,
  showTrails = true,
  showNames = false,
  onSelect,
  onTick,
  tickIntervalMs = 250,
}) {
  // Sized from the enclosing map's own element, which matters when two maps
  // share one viewport in the split comparison.
  const { pxPerUnit } = useMapMetrics()

  const nodesRef = useRef(new Map())
  // Ref callbacks run at commit, never during render, so mutating the map here
  // is safe. Memoised so React does not detach and re-attach every node on
  // each render.
  const registerRef = useCallback((id, slot, el) => {
    const entry = nodesRef.current.get(id) ?? {}
    entry[slot] = el
    nodesRef.current.set(id, entry)
  }, [])

  // The animation loop reads the latest props without being torn down and
  // rebuilt whenever one of them changes. Written in a layout effect rather
  // than during render, so the render pass stays free of side effects.
  const stateRef = useRef({
    ships,
    geometries,
    running,
    timeScale,
    pxPerUnit,
    showTrails,
    showNames,
    onTick,
    tickIntervalMs,
  })
  useLayoutEffect(() => {
    stateRef.current = {
      ships,
      geometries,
      running,
      timeScale,
      pxPerUnit,
      showTrails,
      showNames,
      onTick,
      tickIntervalMs,
    }
  })

  useEffect(() => {
    let frame = 0
    let lastTs = 0
    let lastTick = 0

    const draw = (ts) => {
      frame = requestAnimationFrame(draw)
      const s = stateRef.current
      const dt = lastTs ? Math.min((ts - lastTs) / 1000, 0.25) : 0
      lastTs = ts
      if (s.running) clockRef.current.hours += dt * s.timeScale

      const hours = clockRef.current.hours
      // A vessel icon should stay the same size on screen at every zoom level.
      // The shape is 26 units tall, so this makes it MARKER_PX tall whatever
      // the viewBox is.
      const markerScale = Math.max(0.02, MARKER_PX / (26 * s.pxPerUnit))
      const fontPx = 11
      const fontUnits = fontPx / s.pxPerUnit

      for (const ship of s.ships) {
        const nodes = nodesRef.current.get(ship.id)
        const geometry = s.geometries[ship.laneName]
        if (!nodes || !geometry) continue

        const state = voyageState(ship, hours)
        const { x, y, heading } = positionAt(geometry, state.nm)
        const facing = state.inbound ? heading + 180 : heading

        nodes.body?.setAttribute('transform', `translate(${x.toFixed(3)} ${y.toFixed(3)})`)
        nodes.hull?.setAttribute(
          'transform',
          `rotate(${facing.toFixed(1)}) scale(${markerScale.toFixed(4)})`,
        )

        if (nodes.trail) {
          if (s.showTrails && !state.berthed) {
            const sailed = state.inbound ? ship.distanceNm * state.progress : state.nm
            nodes.trail.setAttribute(
              'd',
              trailPath(geometry, state.nm, Math.min(sailed, ship.distanceNm * 0.22)),
            )
            nodes.trail.setAttribute('stroke-width', (2.2 / s.pxPerUnit).toFixed(3))
            nodes.trail.setAttribute('visibility', 'visible')
          } else {
            nodes.trail.setAttribute('visibility', 'hidden')
          }
        }

        if (nodes.label) {
          if (s.showNames) {
            nodes.label.setAttribute('x', x.toFixed(3))
            nodes.label.setAttribute('y', (y - (18 / s.pxPerUnit)).toFixed(3))
            nodes.label.setAttribute('font-size', fontUnits.toFixed(3))
            nodes.label.setAttribute('stroke-width', (fontUnits * 0.16).toFixed(3))
            nodes.label.textContent = ship.vesselName
            nodes.label.setAttribute('visibility', 'visible')
          } else {
            nodes.label.setAttribute('visibility', 'hidden')
          }
        }
      }

      if (s.onTick && ts - lastTick >= s.tickIntervalMs) {
        lastTick = ts
        s.onTick(hours, s.ships.map((ship) => snapshotShip(ship, hours)))
      }
    }

    frame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(frame)
  }, [clockRef])

  return (
    <g>
      {ships.map((ship) => (
        <ShipMarker
          key={ship.id}
          ship={ship}
          selected={ship.id === selectedId}
          dimmed={Boolean(dimmedIds?.size) && dimmedIds.has(ship.id)}
          onSelect={onSelect}
          registerRef={registerRef}
        />
      ))}
    </g>
  )
}
