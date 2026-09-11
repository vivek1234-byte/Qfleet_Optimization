/**
 * The base map: coastlines, graticule, ports, chokepoints, lanes.
 *
 * Everything is inline SVG drawn from data baked into the bundle. There is no
 * tile server, no map library and no network call, because the demo has to
 * survive a venue with no usable Wi-Fi.
 *
 * The coordinate system throughout is "map units": one unit is one degree,
 * x = longitude + 180 and y = 90 - latitude. Stroke widths are therefore in
 * degrees too, which is why they look tiny — the viewBox does the scaling.
 */
import { memo, useCallback, useEffect, useRef, useState } from 'react'

import { CHOKEPOINTS, project } from '../data/geography'
import LAND_PATH from '../data/land'
import { beaufortColor } from '../lib/domain'
import { cx } from './ui'

/* -------------------------------------------------------------------------- */
/* Static layers                                                               */
/* -------------------------------------------------------------------------- */
const Graticule = memo(function Graticule({ step = 15 }) {
  const lines = []
  for (let lon = -180; lon <= 180; lon += step) {
    const x = lon + 180
    lines.push(<line key={`v${lon}`} x1={x} y1={0} x2={x} y2={180} />)
  }
  for (let lat = -75; lat <= 75; lat += step) {
    const y = 90 - lat
    lines.push(<line key={`h${lat}`} x1={0} y1={y} x2={360} y2={y} />)
  }
  return (
    <g
      stroke="rgb(var(--map-graticule))"
      strokeWidth={0.08}
      opacity={0.9}
      pointerEvents="none"
      aria-hidden
    >
      {lines}
    </g>
  )
})

const Land = memo(function Land() {
  // Three copies so panning past the antimeridian stays seamless.
  return (
    <g pointerEvents="none" aria-hidden>
      {[-360, 0, 360].map((dx) => (
        <path
          key={dx}
          transform={dx ? `translate(${dx},0)` : undefined}
          d={LAND_PATH}
          fill="rgb(var(--map-land))"
          stroke="rgb(var(--map-coast))"
          strokeWidth={0.12}
          strokeLinejoin="round"
        />
      ))}
    </g>
  )
})

/* -------------------------------------------------------------------------- */
/* Lanes                                                                       */
/* -------------------------------------------------------------------------- */
function LaneLayer({ lanes, geometries, activeLanes, colorBy, paused, onSelectLane }) {
  return (
    <g>
      {lanes.map((lane) => {
        const geometry = geometries[lane.name]
        if (!geometry) return null
        const active = !activeLanes || activeLanes.has(lane.name)
        const stroke = colorBy === 'weather' ? beaufortColor(lane.typical_beaufort) : '#3b82f6'
        return (
          <g key={lane.name} opacity={active ? 1 : 0.18}>
            {/* Wide invisible hit area — a 0.2-unit line is impossible to click. */}
            <path
              d={geometry.d}
              fill="none"
              stroke="transparent"
              strokeWidth={1.6}
              style={{ cursor: onSelectLane ? 'pointer' : 'default' }}
              onClick={onSelectLane ? () => onSelectLane(lane.name) : undefined}
            >
              <title>
                {lane.name} · {lane.distance_nm.toLocaleString()} nm
                {lane.via ? ` via ${lane.via}` : ''}
              </title>
            </path>
            <path
              d={geometry.d}
              fill="none"
              stroke={stroke}
              strokeWidth={0.22}
              strokeOpacity={active ? 0.45 : 0.3}
              strokeLinecap="round"
            />
            {active && (
              <path
                d={geometry.d}
                fill="none"
                stroke={stroke}
                strokeWidth={0.3}
                strokeOpacity={0.95}
                strokeLinecap="round"
                className={cx('lane-flow', paused && 'is-paused')}
              />
            )}
          </g>
        )
      })}
    </g>
  )
}

/* -------------------------------------------------------------------------- */
/* Ports                                                                       */
/* -------------------------------------------------------------------------- */
function PortLayer({ ports, showLabels, scale, activePorts }) {
  const r = Math.max(0.22, 0.75 / Math.sqrt(scale))
  const fontSize = Math.max(0.7, 2.6 / Math.sqrt(scale))
  return (
    <g>
      {ports.map(({ name, lat, lon, side, country, dy = 0 }) => {
        const [x, y] = project([lat, lon])
        const active = !activePorts || activePorts.has(name)
        const anchor = side === 'right' ? 'start' : 'end'
        const dx = side === 'right' ? r * 1.8 : -r * 1.8
        // Ports a few kilometres apart need their labels pulled apart, but the
        // nudge is in degrees, so scale it with the zoom or it vanishes.
        const nudge = dy * Math.max(fontSize / 1.4, 0.35)
        return (
          <g key={name} opacity={active ? 1 : 0.35}>
            {active && (
              <circle cx={x} cy={y} fill="none" stroke="#38bdf8" strokeWidth={0.12} className="pulse-ring" />
            )}
            <circle
              cx={x}
              cy={y}
              r={r}
              fill={active ? '#e2f4ff' : '#7b93ad'}
              stroke="#0b1c2e"
              strokeWidth={r * 0.35}
            >
              <title>
                {name}, {country}
              </title>
            </circle>
            {showLabels && (
              <text
                x={x + dx}
                y={y + fontSize * 0.34 + nudge}
                textAnchor={anchor}
                fontSize={fontSize}
                fill="#dbeafe"
                stroke="rgb(var(--map-ocean))"
                strokeWidth={fontSize * 0.18}
                paintOrder="stroke"
                style={{ pointerEvents: 'none', fontWeight: 600 }}
              >
                {name}
              </text>
            )}
          </g>
        )
      })}
    </g>
  )
}

function ChokepointLayer({ scale }) {
  const fontSize = Math.max(0.6, 2.1 / Math.sqrt(scale))
  return (
    <g pointerEvents="none" aria-hidden>
      {CHOKEPOINTS.map(({ name, lat, lon }) => {
        const [x, y] = project([lat, lon])
        return (
          <g key={name}>
            <path
              d={`M${x - 0.6} ${y} L${x + 0.6} ${y} M${x} ${y - 0.6} L${x} ${y + 0.6}`}
              stroke="#facc15"
              strokeWidth={0.1}
              opacity={0.75}
            />
            <text
              x={x}
              y={y - fontSize * 0.7}
              textAnchor="middle"
              fontSize={fontSize * 0.82}
              fill="#fde68a"
              stroke="rgb(var(--map-ocean))"
              strokeWidth={fontSize * 0.14}
              paintOrder="stroke"
              style={{ fontStyle: 'italic' }}
            >
              {name}
            </text>
          </g>
        )
      })}
    </g>
  )
}

/* -------------------------------------------------------------------------- */
/* Pan and zoom                                                                */
/* -------------------------------------------------------------------------- */
/**
 * viewBox-based pan/zoom.
 *
 * Pointer events are used rather than mouse events so the map works on a
 * touchscreen, which matters when the judges want to drive it themselves.
 */
export function useMapViewport(initialBox, { minSpan = 6, maxSpan = 360 } = {}) {
  const [box, setBox] = useState(initialBox)
  const svgRef = useRef(null)
  const dragRef = useRef(null)

  const reset = useCallback((next) => setBox(next ?? initialBox), [initialBox])

  /** Convert a client point to map units using the current viewBox. */
  const toMap = useCallback(
    (clientX, clientY) => {
      const svg = svgRef.current
      if (!svg) return null
      const rect = svg.getBoundingClientRect()
      const [bx, by, bw, bh] = box
      // The SVG uses preserveAspectRatio="xMidYMid meet", so the drawn area is
      // letterboxed inside the element; account for that or the cursor drifts.
      const scale = Math.min(rect.width / bw, rect.height / bh)
      const drawnW = bw * scale
      const drawnH = bh * scale
      const offsetX = (rect.width - drawnW) / 2
      const offsetY = (rect.height - drawnH) / 2
      return [
        bx + (clientX - rect.left - offsetX) / scale,
        by + (clientY - rect.top - offsetY) / scale,
      ]
    },
    [box],
  )

  const zoomAt = useCallback(
    (factor, clientX, clientY) => {
      const anchor = toMap(clientX, clientY)
      setBox(([bx, by, bw, bh]) => {
        const nextW = Math.min(maxSpan, Math.max(minSpan, bw * factor))
        const k = nextW / bw
        const nextH = bh * k
        if (!anchor) return [bx, by, nextW, nextH]
        const [ax, ay] = anchor
        return [ax - (ax - bx) * k, ay - (ay - by) * k, nextW, nextH]
      })
    },
    [toMap, minSpan, maxSpan],
  )

  const onWheel = useCallback(
    (event) => {
      event.preventDefault()
      zoomAt(Math.exp(event.deltaY * 0.0016), event.clientX, event.clientY)
    },
    [zoomAt],
  )

  // React attaches wheel listeners passively, which makes preventDefault a
  // no-op and lets the page scroll instead of the map zooming.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return undefined
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [onWheel])

  const onPointerDown = useCallback(
    (event) => {
      if (event.button !== 0) return
      const svg = svgRef.current
      if (!svg) return
      const rect = svg.getBoundingClientRect()
      const [, , bw, bh] = box
      // Pixels-per-map-unit at drag start. Held fixed for the whole drag, so
      // panning stays 1:1 with the pointer instead of accelerating.
      const unitsPerPixel = 1 / Math.min(rect.width / bw, rect.height / bh)
      dragRef.current = { clientX: event.clientX, clientY: event.clientY, box, unitsPerPixel }
      event.currentTarget.setPointerCapture?.(event.pointerId)
    },
    [box],
  )

  const onPointerMove = useCallback((event) => {
    const drag = dragRef.current
    if (!drag) return
    const [bx, by, bw, bh] = drag.box
    const dx = (event.clientX - drag.clientX) * drag.unitsPerPixel
    const dy = (event.clientY - drag.clientY) * drag.unitsPerPixel
    setBox([bx - dx, by - dy, bw, bh])
  }, [])

  const endDrag = useCallback((event) => {
    dragRef.current = null
    event.currentTarget.releasePointerCapture?.(event.pointerId)
  }, [])

  // Rendered size, so callers can keep vessel markers a constant number of
  // pixels tall however far the map is zoomed.
  const [pixelWidth, setPixelWidth] = useState(1000)
  useEffect(() => {
    const svg = svgRef.current
    if (!svg || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setPixelWidth(width)
    })
    observer.observe(svg)
    return () => observer.disconnect()
  }, [])

  const handlers = { onPointerDown, onPointerMove, onPointerUp: endDrag, onPointerLeave: endDrag }
  const scale = 360 / box[2]
  const pxPerUnit = pixelWidth / box[2]

  return { box, setBox, reset, svgRef, handlers, scale, pxPerUnit, zoomAt }
}

/* -------------------------------------------------------------------------- */
/* Map frame                                                                   */
/* -------------------------------------------------------------------------- */
export default function WorldMap({
  viewport,
  lanes = [],
  geometries = {},
  ports = [],
  activeLanes,
  activePorts,
  showPortLabels = true,
  showChokepoints = true,
  showGraticule = true,
  laneColorBy = 'uniform',
  paused = false,
  onSelectLane,
  className,
  children,
}) {
  const { box, svgRef, handlers, scale } = viewport

  return (
    <svg
      ref={svgRef}
      viewBox={box.join(' ')}
      preserveAspectRatio="xMidYMid meet"
      className={cx('map-surface h-full w-full touch-none select-none', className)}
      style={{ cursor: 'grab' }}
      role="img"
      aria-label="World map of fleet trade lanes and vessel positions"
      {...handlers}
    >
      <defs>
        <filter id="ship-glow" x="-120%" y="-120%" width="340%" height="340%">
          <feGaussianBlur stdDeviation="0.35" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Flat ocean. A radial vignette here looked better in principle but
          tiled visibly in Chromium once the viewBox was zoomed in. */}
      <rect x={-720} y={-180} width={1800} height={540} fill="rgb(var(--map-ocean))" />
      {showGraticule && <Graticule />}
      <Land />
      <LaneLayer
        lanes={lanes}
        geometries={geometries}
        activeLanes={activeLanes}
        colorBy={laneColorBy}
        paused={paused}
        onSelectLane={onSelectLane}
      />
      {showChokepoints && <ChokepointLayer scale={scale} />}
      <PortLayer ports={ports} showLabels={showPortLabels} scale={scale} activePorts={activePorts} />
      {children}
    </svg>
  )
}
