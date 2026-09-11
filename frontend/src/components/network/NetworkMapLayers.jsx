/**
 * Extra SVG layers for the dashboard's network map.
 *
 * Two things the base `WorldMap` does not do: draw the planned fleet as
 * static, selectable markers, and render flow along the lanes.
 *
 * **On flow:** the obvious implementation is a particle per dot per lane,
 * which at sixteen lanes is a few hundred SVG nodes animating on the
 * dashboard's main thread while a Recharts panel sits next to it. This uses
 * one extra `<path>` per lane instead, with a round-capped dash pattern that
 * reads as travelling dots. Sixteen nodes, animated by the compositor, and it
 * inherits the global `prefers-reduced-motion` rule in index.css for free.
 *
 * **On vessel positions:** a plan assigns a ship to a lane. It does not say
 * where that ship is at this moment, and this project has no AIS feed. So
 * markers are spaced deterministically along the lane rather than drifting —
 * a moving marker would be asserting a position the data does not contain.
 * The live simulator is where motion belongs, because there a clock is
 * actually driving it.
 */
import { memo, useMemo } from 'react'

import { useMapMetrics } from '../WorldMap'
import { positionAt } from '../../data/geography'
import { fuelColor } from '../../lib/domain'

const EMPTY = []

/** Colour per lane state. Muted on purpose — state should read, not shout. */
export const LANE_STATE_STROKE = {
  normal: '#3b82f6',
  optimised: '#34d399',
  pressure: '#fbbf24',
  intensive: '#fb923c',
}

/* -------------------------------------------------------------------------- */
/* Flow                                                                        */
/* -------------------------------------------------------------------------- */
export const FlowLayer = memo(function FlowLayer({
  lanes = EMPTY,
  geometries = {},
  laneStates = {},
  running = true,
  emphasis = EMPTY,
}) {
  const emphasised = useMemo(() => new Set(emphasis), [emphasis])
  return (
    <g aria-hidden>
      {lanes.map((lane) => {
        const geometry = geometries[lane.name]
        if (!geometry) return null
        const state = laneStates[lane.name] ?? 'normal'
        const hot = emphasised.size === 0 || emphasised.has(lane.name)
        return (
          <path
            key={lane.name}
            d={geometry.d}
            fill="none"
            stroke={LANE_STATE_STROKE[state] ?? LANE_STATE_STROKE.normal}
            strokeWidth={hot ? 0.34 : 0.2}
            strokeOpacity={hot ? 0.9 : 0.25}
            strokeLinecap="round"
            className={running ? 'lane-particles' : undefined}
            style={running ? undefined : { strokeDasharray: 'none', opacity: 0 }}
          />
        )
      })}
    </g>
  )
})

/* -------------------------------------------------------------------------- */
/* Vessels                                                                     */
/* -------------------------------------------------------------------------- */
/**
 * One marker per assigned vessel, coloured by fuel so the map reads as a fuel
 * map at a glance without a second legend.
 */
export const VesselLayer = memo(function VesselLayer({
  vessels = EMPTY,
  geometries = {},
  selectedId,
  dimmed,
  onSelect,
  onHover,
}) {
  const { pxPerUnit } = useMapMetrics()
  // Markers stay a constant size on screen however far the map is zoomed —
  // otherwise they vanish at world scale and swamp the coastline up close.
  const r = 6.5 / Math.max(pxPerUnit, 0.001)
  const ring = 11 / Math.max(pxPerUnit, 0.001)

  const placed = useMemo(() => {
    const perLane = new Map()
    vessels.forEach((v) => {
      const list = perLane.get(v.lane) ?? []
      list.push(v)
      perLane.set(v.lane, list)
    })

    const out = []
    perLane.forEach((list, laneName) => {
      const geometry = geometries[laneName]
      if (!geometry) return
      list.forEach((vessel, index) => {
        // Spread evenly along the lane, deterministic in the vessel's order.
        const fraction = (index + 0.5) / list.length
        const point = positionAt(geometry, geometry.totalNm * fraction)
        if (!point) return
        out.push({ ...vessel, x: point.x, y: point.y, heading: point.heading })
      })
    })
    return out
  }, [vessels, geometries])

  return (
    <g>
      {placed.map((vessel) => {
        const isDim = dimmed?.size ? dimmed.has(vessel.id) : false
        const isSelected = selectedId === vessel.id
        const color = fuelColor(vessel.fuel)
        return (
          <g
            key={vessel.id}
            transform={`translate(${vessel.x} ${vessel.y})`}
            opacity={isDim ? 0.2 : 1}
            className="ship-marker"
            style={{ cursor: 'pointer' }}
            onClick={(event) => {
              event.stopPropagation()
              onSelect?.(vessel)
            }}
            onMouseEnter={() => onHover?.(vessel)}
            onMouseLeave={() => onHover?.(null)}
            onFocus={() => onHover?.(vessel)}
            onBlur={() => onHover?.(null)}
            tabIndex={0}
            role="button"
            aria-label={`${vessel.name}, ${vessel.type}, ${vessel.route}`}
          >
            {isSelected && (
              <circle r={ring} fill="none" stroke="#38bdf8" strokeWidth={ring * 0.16} opacity={0.9} />
            )}
            {/* Generous transparent hit area — the visible dot is ~5px. */}
            <circle r={ring * 1.1} fill="transparent" />
            <circle r={r} fill={color} stroke="#04121f" strokeWidth={r * 0.34} filter="url(#ship-glow)" />
          </g>
        )
      })}
    </g>
  )
})

export default VesselLayer
