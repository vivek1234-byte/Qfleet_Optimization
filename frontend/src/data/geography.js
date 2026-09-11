/**
 * Port positions and navigable sea routes for the sixteen registry lanes.
 *
 * The backend registry knows a lane's distance but not its shape. Drawing a
 * straight line from Mundra to Rotterdam would take the ship over the Sahara,
 * so every lane carries hand-placed sea waypoints: Bab-el-Mandeb and the Suez
 * Canal for Europe, the Malacca Strait for East Asia, the Mozambique Channel
 * for Durban. Lane names are the key and must match `/api/optimization/registry`
 * exactly.
 *
 * Coordinates are [latitude, longitude] in degrees.
 */

/**
 * Ports.
 *
 * `side` puts the label left or right of the marker. `dy` nudges it up or
 * down in degrees, which is needed where two ports are almost on top of each
 * other — Nhava Sheva and Mumbai are eleven kilometres apart, and Kandla and
 * Mundra not much more, so without the nudge their labels overprint.
 */
export const PORTS = {
  'Nhava Sheva': { lat: 18.95, lon: 72.95, country: 'India', side: 'left', dy: -1.3 },
  Mumbai: { lat: 18.94, lon: 72.84, country: 'India', side: 'left', dy: 1.7 },
  Mundra: { lat: 22.74, lon: 69.7, country: 'India', side: 'left', dy: 1.5 },
  Kandla: { lat: 23.02, lon: 70.22, country: 'India', side: 'right', dy: -1.4 },
  Chennai: { lat: 13.09, lon: 80.29, country: 'India', side: 'right' },
  Visakhapatnam: { lat: 17.69, lon: 83.3, country: 'India', side: 'right' },
  Paradip: { lat: 20.26, lon: 86.68, country: 'India', side: 'right', dy: 0.9 },
  Kochi: { lat: 9.97, lon: 76.26, country: 'India', side: 'left' },
  Haldia: { lat: 22.03, lon: 88.09, country: 'India', side: 'right', dy: -0.9 },
  Mormugao: { lat: 15.4, lon: 73.8, country: 'India', side: 'left' },
  Singapore: { lat: 1.26, lon: 103.83, country: 'Singapore', side: 'right', dy: 1.4 },
  Rotterdam: { lat: 51.95, lon: 4.14, country: 'Netherlands', side: 'right', dy: -1.2 },
  Felixstowe: { lat: 51.96, lon: 1.35, country: 'United Kingdom', side: 'left', dy: 1.4 },
  'Jebel Ali': { lat: 25.01, lon: 55.06, country: 'UAE', side: 'left' },
  Colombo: { lat: 6.95, lon: 79.84, country: 'Sri Lanka', side: 'left' },
  Shanghai: { lat: 31.23, lon: 121.8, country: 'China', side: 'right' },
  'Port Klang': { lat: 3.0, lon: 101.39, country: 'Malaysia', side: 'left' },
  Qingdao: { lat: 36.07, lon: 120.32, country: 'China', side: 'right' },
  Jeddah: { lat: 21.48, lon: 39.18, country: 'Saudi Arabia', side: 'left' },
  Durban: { lat: -29.87, lon: 31.03, country: 'South Africa', side: 'left' },
  Yangon: { lat: 16.77, lon: 96.17, country: 'Myanmar', side: 'right' },
  'Dar es Salaam': { lat: -6.82, lon: 39.29, country: 'Tanzania', side: 'left' },
  Jakarta: { lat: -6.1, lon: 106.88, country: 'Indonesia', side: 'right' },
  Jinzhou: { lat: 40.8, lon: 121.05, country: 'China', side: 'right' },
}

/**
 * Named chokepoints. Drawn on the map because "the route goes through Suez"
 * is the single fastest way to convince a maritime reviewer the geometry is
 * not decorative.
 */
export const CHOKEPOINTS = [
  { name: 'Suez Canal', lat: 30.5, lon: 32.35 },
  { name: 'Bab-el-Mandeb', lat: 12.6, lon: 43.4 },
  { name: 'Strait of Hormuz', lat: 26.3, lon: 56.5 },
  { name: 'Malacca Strait', lat: 3.5, lon: 99.5 },
  { name: 'Gibraltar', lat: 35.95, lon: -5.6 },
  { name: 'Dover Strait', lat: 50.9, lon: 1.5 },
  { name: 'Mozambique Channel', lat: -18.0, lon: 41.5 },
  { name: 'Sunda Strait', lat: -5.9, lon: 105.6 },
]

/* Reusable waypoint runs, so the Suez legs stay identical between lanes. */
const ARABIAN_SEA_W = [
  [21.0, 66.0],
  [16.0, 60.0],
  [13.5, 52.0],
]
const RED_SEA = [
  [12.6, 43.4],
  [15.5, 41.4],
  [20.0, 38.5],
  [25.0, 36.0],
  [27.6, 34.2],
  [29.4, 32.6],
]
const SUEZ_TO_GIBRALTAR = [
  [31.3, 32.3],
  [33.2, 28.0],
  [34.6, 22.0],
  [36.3, 15.0],
  [37.4, 10.0],
  [37.6, 4.0],
  [36.6, -1.0],
  [35.95, -5.6],
]
const GIBRALTAR_TO_DOVER = [
  [36.4, -9.4],
  [41.0, -10.2],
  [45.5, -8.6],
  [48.4, -6.0],
  [49.9, -2.5],
  [50.6, 0.6],
  [50.95, 1.6],
]
const DONDRA_TO_MALACCA = [
  [5.6, 80.8],
  [5.8, 88.0],
  [5.9, 94.0],
  [5.4, 97.6],
  [3.6, 100.2],
  [2.0, 102.4],
]
const MALACCA_TO_EAST_CHINA = [
  [1.4, 104.2],
  [4.5, 106.5],
  [10.0, 109.0],
  [15.5, 112.0],
  [20.5, 115.5],
  [24.5, 119.5],
  [28.0, 122.5],
]

/**
 * Lane geometry keyed by the registry lane name.
 * `waypoints` are intermediate sea positions; the origin and destination port
 * coordinates are prepended and appended automatically.
 */
export const LANE_WAYPOINTS = {
  'JNPT – Singapore': [[14.5, 72.0], [8.5, 75.0], ...DONDRA_TO_MALACCA],
  'Mundra – Rotterdam': [
    ...ARABIAN_SEA_W,
    ...RED_SEA,
    ...SUEZ_TO_GIBRALTAR,
    ...GIBRALTAR_TO_DOVER,
    [51.5, 3.0],
  ],
  'JNPT – Jebel Ali': [
    [20.5, 68.5],
    [23.5, 62.5],
    [25.2, 58.0],
    [26.3, 56.5],
    [25.9, 55.6],
  ],
  // Adam's Bridge closes the Palk Strait to deep-draught ships, so Chennai to
  // Colombo rounds Dondra Head rather than cutting inside Sri Lanka.
  'Chennai – Colombo': [
    [10.5, 81.5],
    [7.5, 82.3],
    [5.6, 81.2],
    [5.5, 79.9],
  ],
  'Mundra – Shanghai': [
    [20.5, 67.5],
    [13.0, 69.5],
    [8.0, 74.5],
    ...DONDRA_TO_MALACCA,
    ...MALACCA_TO_EAST_CHINA,
    [30.5, 123.0],
  ],
  'Visakhapatnam – Port Klang': [
    [14.5, 85.5],
    [9.0, 90.5],
    [6.2, 95.5],
    [5.3, 97.8],
    [3.8, 100.0],
  ],
  'Paradip – Qingdao': [
    [18.0, 88.0],
    [11.5, 92.5],
    [6.5, 96.0],
    [5.2, 97.8],
    [2.2, 102.2],
    ...MALACCA_TO_EAST_CHINA,
    [31.5, 124.0],
    [34.5, 123.0],
  ],
  'Kandla – Jeddah': [...ARABIAN_SEA_W, [12.4, 45.0], [12.6, 43.4], [15.5, 41.3], [18.5, 40.0]],
  'Mumbai – Durban': [
    [15.0, 70.0],
    [8.0, 66.0],
    [1.0, 61.0],
    [-6.0, 54.0],
    [-13.0, 46.5],
    [-18.5, 41.8],
    [-24.0, 37.0],
    [-28.0, 33.0],
  ],
  'Kochi – Jeddah': [
    [9.0, 72.0],
    [11.0, 64.0],
    [12.6, 55.0],
    [12.4, 45.5],
    [12.6, 43.4],
    [16.0, 41.0],
    [19.5, 39.7],
  ],
  'Haldia – Yangon': [
    [20.6, 88.3],
    [18.0, 89.5],
    [15.5, 92.5],
    [14.8, 95.0],
    [15.6, 95.9],
  ],
  'Kandla – Dar es Salaam': [
    [20.5, 66.5],
    [13.5, 60.0],
    [6.0, 55.0],
    [-1.0, 49.0],
    [-5.5, 42.5],
  ],
  'Chennai – Jakarta': [
    [9.5, 83.5],
    [6.0, 90.0],
    [5.7, 94.5],
    [5.4, 97.6],
    [3.6, 100.2],
    [2.0, 102.4],
    [1.1, 104.4],
    [-1.5, 105.6],
    [-4.6, 106.1],
  ],
  'Mormugao – Jinzhou': [
    [13.5, 72.8],
    [8.0, 76.5],
    ...DONDRA_TO_MALACCA,
    ...MALACCA_TO_EAST_CHINA,
    [31.5, 124.0],
    [35.0, 123.5],
    [38.0, 122.0],
  ],
  'JNPT – Felixstowe': [
    [16.0, 69.5],
    ...ARABIAN_SEA_W.slice(1),
    ...RED_SEA,
    ...SUEZ_TO_GIBRALTAR,
    ...GIBRALTAR_TO_DOVER,
    [51.7, 2.1],
  ],
  'Visakhapatnam – Singapore': [
    [14.5, 86.0],
    [9.5, 91.0],
    [6.3, 95.5],
    [5.3, 97.8],
    [3.6, 100.2],
    [2.0, 102.4],
  ],
}

/* -------------------------------------------------------------------------- */
/* Projection                                                                  */
/* -------------------------------------------------------------------------- */
/** Equirectangular map units. x = lon + 180, y = 90 - lat. */
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

/**
 * Build the drawable, measurable path for a lane.
 *
 * The registry's `distance_nm` is the authoritative sea distance (it matches
 * published port-to-port tables). The drawn polyline is close but not equal to
 * it, so segment lengths are rescaled to sum to the registry figure — that way
 * a ship's position on screen and its progress percentage never disagree.
 */
export function buildLaneGeometry(lane) {
  const origin = PORTS[lane.origin]
  const destination = PORTS[lane.destination]
  if (!origin || !destination) return null

  const mid = LANE_WAYPOINTS[lane.name] ?? []
  const points = [
    [origin.lat, origin.lon],
    ...mid,
    [destination.lat, destination.lon],
  ]

  const segments = []
  let drawn = 0
  for (let i = 1; i < points.length; i += 1) {
    const nm = haversineNm(points[i - 1], points[i])
    drawn += nm
    segments.push(nm)
  }

  const scale = drawn > 0 && lane.distance_nm > 0 ? lane.distance_nm / drawn : 1
  const cumulative = [0]
  segments.forEach((nm, i) => cumulative.push(cumulative[i] + nm * scale))

  const xy = points.map(project)
  const d = xy.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`).join('')

  return {
    name: lane.name,
    points,
    xy,
    d,
    cumulative,
    totalNm: cumulative[cumulative.length - 1],
    origin,
    destination,
  }
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
  // atan2 on screen coordinates: y grows southward, so this is already a
  // compass bearing once we measure clockwise from north.
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

/** Named map bookmarks for the simulator's zoom presets. */
export const MAP_VIEWS = {
  world: { label: 'World', box: [150, 20, 160, 115] },
  indianOcean: { label: 'Indian Ocean', box: [190, 45, 105, 75] },
  india: { label: 'India', box: [237, 55, 45, 35] },
  arabianSea: { label: 'Arabian Sea & Gulf', box: [210, 55, 60, 40] },
  seAsia: { label: 'SE Asia & China', box: [268, 45, 52, 45] },
  europe: { label: 'Suez to Europe', box: [168, 35, 45, 32] },
}
