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
import {
  createContext,
  memo,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { polygonCentroid, polygonPath, project } from '../data/geography'
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

function ChokepointLayer({ chokepoints, scale }) {
  const fontSize = Math.max(0.6, 2.1 / Math.sqrt(scale))
  return (
    <g pointerEvents="none" aria-hidden>
      {chokepoints.map(({ name, lat, lon }) => {
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
/* Emission control areas                                                      */
/* -------------------------------------------------------------------------- */
/**
 * MARPOL Annex VI zones. Inside one, fuel sulphur is capped at 0.10%, so a
 * ship on residual fuel has to switch to distillate — which is why the two
 * European lanes are the expensive ones for a dirty fleet.
 *
 * Outlines are indicative, as the API says when it serves them. Drawn under
 * the lanes so a route stays legible crossing one.
 */
const EcaLayer = memo(function EcaLayer({ zones, scale, showLabels = true }) {
  const fontSize = Math.max(0.8, 3.0 / Math.sqrt(scale))
  return (
    <g pointerEvents="none">
      {zones.map((zone) => {
        const d = polygonPath(zone.polygon)
        if (!d) return null
        const centre = polygonCentroid(zone.polygon)
        return (
          <g key={zone.short_name}>
            <path
              d={d}
              fill="#f97316"
              fillOpacity={0.1}
              stroke="#fb923c"
              strokeWidth={0.16}
              strokeDasharray="1.4 1"
              strokeOpacity={0.75}
            />
            {showLabels && centre && (
              <text
                x={centre[0]}
                y={centre[1]}
                textAnchor="middle"
                fontSize={fontSize}
                fill="#fdba74"
                fillOpacity={0.85}
                stroke="rgb(var(--map-ocean))"
                strokeWidth={fontSize * 0.12}
                paintOrder="stroke"
                style={{ fontWeight: 600, letterSpacing: '0.04em' }}
              >
                {zone.short_name}
              </text>
            )}
          </g>
        )
      })}
    </g>
  )
})

/* -------------------------------------------------------------------------- */
/* Pan and zoom                                                                */
/* -------------------------------------------------------------------------- */
/**
 * Shared viewport state.
 *
 * Deliberately owns the viewBox and nothing else. The split-screen comparison
 * puts two maps on one viewport so they pan and zoom together, which means
 * anything measured in pixels — the element rect, its width — belongs to the
 * individual map, not to the shared state. Keeping the DOM ref here was a bug:
 * the second map to mount overwrote the first, so vessel markers were sized
 * from the wrong element and dragging the left pane computed its offset from
 * the right pane's rectangle.
 */
export function useMapViewport(initialBox, { minSpan = 6, maxSpan = 360 } = {}) {
  const [box, setBox] = useState(initialBox)

  const reset = useCallback((next) => setBox(next ?? initialBox), [initialBox])

  /** Zoom about a point given in map units. */
  const zoomAtPoint = useCallback(
    (factor, anchor) => {
      setBox(([bx, by, bw, bh]) => {
        const nextW = Math.min(maxSpan, Math.max(minSpan, bw * factor))
        const k = nextW / bw
        const nextH = bh * k
        if (!anchor) return [bx, by, nextW, nextH]
        const [ax, ay] = anchor
        return [ax - (ax - bx) * k, ay - (ay - by) * k, nextW, nextH]
      })
    },
    [minSpan, maxSpan],
  )

  /** Zoom about the centre of the current view — what a button should do. */
  const zoomBy = useCallback(
    (factor) =>
      setBox(([bx, by, bw, bh]) => {
        const nextW = Math.min(maxSpan, Math.max(minSpan, bw * factor))
        const k = nextW / bw
        const nextH = bh * k
        return [bx + (bw - nextW) / 2, by + (bh - nextH) / 2, nextW, nextH]
      }),
    [minSpan, maxSpan],
  )

  const scale = 360 / box[2]

  return { box, setBox, reset, zoomAtPoint, zoomBy, scale }
}

/**
 * Everything about one rendered map that is measured in pixels.
 *
 * Each map instance has its own element, so each gets its own observer and its
 * own pointer handlers, even when several share a viewport.
 */
function useMapElement(viewport) {
  const { box, setBox, zoomAtPoint } = viewport
  const svgRef = useRef(null)
  const dragRef = useRef(null)
  const [pixelWidth, setPixelWidth] = useState(1000)

  useEffect(() => {
    const svg = svgRef.current
    if (!svg || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(([entry]) => {
      const { width } = entry.contentRect
      if (width > 0) setPixelWidth(width)
    })
    observer.observe(svg)
    return () => observer.disconnect()
  }, [])

  /** Client point to map units, for this element's own rectangle. */
  const toMap = useCallback(
    (clientX, clientY) => {
      const svg = svgRef.current
      if (!svg) return null
      const rect = svg.getBoundingClientRect()
      const [bx, by, bw, bh] = box
      // preserveAspectRatio letterboxes the drawn area inside the element;
      // ignore that and the cursor drifts away from the point it grabbed.
      const scale = Math.min(rect.width / bw, rect.height / bh)
      const offsetX = (rect.width - bw * scale) / 2
      const offsetY = (rect.height - bh * scale) / 2
      return [
        bx + (clientX - rect.left - offsetX) / scale,
        by + (clientY - rect.top - offsetY) / scale,
      ]
    },
    [box],
  )

  const onWheel = useCallback(
    (event) => {
      event.preventDefault()
      zoomAtPoint(Math.exp(event.deltaY * 0.0016), toMap(event.clientX, event.clientY))
    },
    [zoomAtPoint, toMap],
  )

  // React attaches wheel listeners passively, which makes preventDefault a
  // no-op and scrolls the page instead of zooming the map.
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
      // Pixels-per-map-unit fixed for the whole drag, so panning tracks the
      // pointer 1:1 instead of accelerating as the view changes.
      const unitsPerPixel = 1 / Math.min(rect.width / bw, rect.height / bh)
      dragRef.current = { clientX: event.clientX, clientY: event.clientY, box, unitsPerPixel }
      event.currentTarget.setPointerCapture?.(event.pointerId)
    },
    [box],
  )

  const onPointerMove = useCallback(
    (event) => {
      const drag = dragRef.current
      if (!drag) return
      const [bx, by, bw, bh] = drag.box
      setBox([
        bx - (event.clientX - drag.clientX) * drag.unitsPerPixel,
        by - (event.clientY - drag.clientY) * drag.unitsPerPixel,
        bw,
        bh,
      ])
    },
    [setBox],
  )

  const endDrag = useCallback((event) => {
    dragRef.current = null
    event.currentTarget.releasePointerCapture?.(event.pointerId)
  }, [])

  return {
    svgRef,
    handlers: { onPointerDown, onPointerMove, onPointerUp: endDrag, onPointerLeave: endDrag },
    pxPerUnit: pixelWidth / box[2],
  }
}

/**
 * Pixels per map unit for the enclosing map.
 *
 * Passed by context rather than as a prop because the things that need it —
 * the vessel layer, mainly — are handed to `WorldMap` as children, and a map
 * cannot inject props into JSX it was given.
 */
const MapMetricsContext = createContext({ pxPerUnit: 8 })

export function useMapMetrics() {
  return useContext(MapMetricsContext)
}

/* -------------------------------------------------------------------------- */
/* Map frame                                                                   */
/* -------------------------------------------------------------------------- */
export default function WorldMap({
  viewport,
  lanes = [],
  geometries = {},
  ports = [],
  chokepoints = [],
  ecaZones = [],
  activeLanes,
  activePorts,
  showPortLabels = true,
  showChokepoints = true,
  showGraticule = true,
  showEca = false,
  laneColorBy = 'uniform',
  paused = false,
  onSelectLane,
  className,
  children,
}) {
  const { box, scale } = viewport
  const { svgRef, handlers, pxPerUnit } = useMapElement(viewport)
  const metrics = useMemo(() => ({ pxPerUnit }), [pxPerUnit])

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
      {showEca && ecaZones.length > 0 && <EcaLayer zones={ecaZones} scale={scale} />}
      <LaneLayer
        lanes={lanes}
        geometries={geometries}
        activeLanes={activeLanes}
        colorBy={laneColorBy}
        paused={paused}
        onSelectLane={onSelectLane}
      />
      {showChokepoints && chokepoints.length > 0 && (
        <ChokepointLayer chokepoints={chokepoints} scale={scale} />
      )}
      <PortLayer ports={ports} showLabels={showPortLabels} scale={scale} activePorts={activePorts} />
      <MapMetricsContext.Provider value={metrics}>{children}</MapMetricsContext.Provider>
    </svg>
  )
}
