/**
 * Map projection and route geometry.
 *
 * The waypoints themselves used to live here, duplicated from nothing — the
 * backend knew a lane was 6,290 nautical miles but not that it went through
 * Suez. They now live in `backend/data/sea_routes.py` and arrive with the
 * registry, because the optimiser needs them too: emission-control-area
 * exposure is computed from that same geometry, and a route drawn from one
 * source while priced from another is a bug waiting to happen.
 *
 * What stays here is the projection and the interpolation the animation needs
 * sixty times a second, which has no business being a network call.
 *
 * Map units: x = longitude + 180 (0..360), y = 90 - latitude (0..180). One
 * unit is one degree.
 */

/* -------------------------------------------------------------------------- */
/* Projection                                                                  */
/* -------------------------------------------------------------------------- */
export const projectX = (lon) => lon + 180
export const projectY = (lat) => 90 - lat
export const project = ([lat, lon]) => [projectX(lon), projectY(lat)]

/** Great-circle distance in nautical miles. */
export function haversineNm([lat1, lon1], [lat2, lon2]) {
  const toRad = Math.PI / 180
  const dLat = (lat2 - lat1) * toRad
  const dLon = (lon2 - lon1) * toRad
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2
  return 3440.065 * 2 * Math.asin(Math.min(1, Math.sqrt(a)))
}

/* -------------------------------------------------------------------------- */
/* Lane geometry                                                               */
/* -------------------------------------------------------------------------- */
/**
 * Turn a registry lane into something drawable and measurable.
 *
 * `lane.waypoints` and `lane.cumulative_nm` come straight from the API. The
 * cumulative distances are already rescaled server-side to sum to the lane's
 * published distance, so a vessel's position on screen and its reported
 * progress cannot drift apart.
 */
export function buildLaneGeometry(lane) {
  const points = lane?.waypoints
  if (!Array.isArray(points) || points.length < 2) return null

  const xy = points.map(project)
  const d = xy.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`).join('')

  let cumulative = lane.cumulative_nm
  if (!Array.isArray(cumulative) || cumulative.length !== points.length) {
    // Fall back to measuring it ourselves rather than refusing to draw.
    const raw = []
    for (let i = 1; i < points.length; i += 1) raw.push(haversineNm(points[i - 1], points[i]))
    const drawn = raw.reduce((a, b) => a + b, 0)
    const scale = drawn > 0 && lane.distance_nm > 0 ? lane.distance_nm / drawn : 1
    cumulative = [0]
    raw.forEach((nm, i) => cumulative.push(cumulative[i] + nm * scale))
  }

  return {
    name: lane.name,
    points,
    xy,
    d,
    cumulative,
    totalNm: cumulative[cumulative.length - 1],
    ecaFraction: lane.eca_fraction ?? 0,
  }
}

/** Build every lane's geometry once, keyed by name. */
export function buildGeometries(lanes = []) {
  const out = {}
  lanes.forEach((lane) => {
    const geometry = buildLaneGeometry(lane)
    if (geometry) out[lane.name] = geometry
  })
  return out
}

/**
 * Position and heading at `nm` along a lane.
 * Returns map units plus a compass heading in degrees.
 */
export function positionAt(geometry, nm) {
  const { cumulative, xy } = geometry
  const total = geometry.totalNm
  const clamped = Math.max(0, Math.min(nm, total))

  let i = 1
  while (i < cumulative.length - 1 && cumulative[i] < clamped) i += 1
  const spanStart = cumulative[i - 1]
  const spanLength = cumulative[i] - spanStart || 1
  const t = (clamped - spanStart) / spanLength

  const [x0, y0] = xy[i - 1]
  const [x1, y1] = xy[i]
  const x = x0 + (x1 - x0) * t
  const y = y0 + (y1 - y0) * t
  // atan2 on screen coordinates: y grows southward, so measuring clockwise
  // from north gives a compass bearing directly.
  const heading = (Math.atan2(x1 - x0, -(y1 - y0)) * 180) / Math.PI
  return { x, y, heading, segment: i }
}

/** The portion of a lane already sailed, for the wake trail. */
export function trailPath(geometry, nm, lookBackNm = 400) {
  const from = Math.max(0, nm - lookBackNm)
  const start = positionAt(geometry, from)
  const end = positionAt(geometry, nm)
  const mids = geometry.xy
    .slice(start.segment, end.segment)
    .map(([x, y]) => `L${x.toFixed(2)} ${y.toFixed(2)}`)
    .join('')
  return `M${start.x.toFixed(2)} ${start.y.toFixed(2)}${mids}L${end.x.toFixed(2)} ${end.y.toFixed(2)}`
}

/** An ECA outline as an SVG path in map units. */
export function polygonPath(polygon = []) {
  if (polygon.length < 3) return ''
  return (
    polygon
      .map(([lat, lon], i) => {
        const [x, y] = project([lat, lon])
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`
      })
      .join('') + 'Z'
  )
}

/** Centroid of a polygon in map units, for placing its label. */
export function polygonCentroid(polygon = []) {
  if (!polygon.length) return null
  const pts = polygon.map(project)
  const x = pts.reduce((a, p) => a + p[0], 0) / pts.length
  const y = pts.reduce((a, p) => a + p[1], 0) / pts.length
  return [x, y]
}

/* -------------------------------------------------------------------------- */
/* Views                                                                       */
/* -------------------------------------------------------------------------- */
/** Named map bookmarks for the simulator's zoom presets. */
export const MAP_VIEWS = {
  world: { label: 'World', box: [150, 20, 160, 115] },
  indianOcean: { label: 'Indian Ocean', box: [190, 45, 105, 75] },
  india: { label: 'India', box: [237, 55, 45, 35] },
  arabianSea: { label: 'Arabian Sea & Gulf', box: [210, 55, 60, 40] },
  seAsia: { label: 'SE Asia & China', box: [268, 45, 52, 45] },
  europe: { label: 'Suez to Europe', box: [168, 35, 45, 32] },
}

/**
 * Label anchoring for ports that sit almost on top of each other.
 *
 * Nhava Sheva and Mumbai are eleven kilometres apart and Kandla and Mundra
 * not much more, so without a nudge their labels overprint at every useful
 * zoom level. `dy` is in degrees, scaled with the font size at render time.
 */
export const PORT_LABEL_HINTS = {
  'Nhava Sheva': { side: 'left', dy: -1.3 },
  Mumbai: { side: 'left', dy: 1.7 },
  Mundra: { side: 'left', dy: 1.5 },
  Kandla: { side: 'right', dy: -1.4 },
  Chennai: { side: 'right' },
  Visakhapatnam: { side: 'right' },
  Paradip: { side: 'right', dy: 0.9 },
  Kochi: { side: 'left' },
  Haldia: { side: 'right', dy: -0.9 },
  Mormugao: { side: 'left' },
  Singapore: { side: 'right', dy: 1.4 },
  Rotterdam: { side: 'right', dy: -1.2 },
  Felixstowe: { side: 'left', dy: 1.4 },
  'Jebel Ali': { side: 'left' },
  Colombo: { side: 'left' },
  Shanghai: { side: 'right' },
  'Port Klang': { side: 'left' },
  Qingdao: { side: 'right' },
  Jeddah: { side: 'left' },
  Durban: { side: 'left' },
  Yangon: { side: 'right' },
  'Dar es Salaam': { side: 'left' },
  Jakarta: { side: 'right' },
  Jinzhou: { side: 'right' },
}

/** Merge API port positions with the local label hints. */
export function decoratePorts(ports = []) {
  return ports.map((port) => ({ ...port, ...(PORT_LABEL_HINTS[port.name] ?? { side: 'right' }) }))
}
