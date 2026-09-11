/**
 * The single place the frontend talks to the backend.
 *
 * Every endpoint the API exposes has a method here, so no page ever builds a
 * URL by hand. The response interceptor turns the backend's structured error
 * envelope into an `ApiError` carrying a code and per-field messages, which is
 * what lets the forms show an inline message instead of a generic failure.
 */
import axios from 'axios'

// Empty base URL in dev: vite proxies /api to the FastAPI server (vite.config.js).
const baseURL = import.meta.env.VITE_API_BASE_URL || ''

export const http = axios.create({
  baseURL,
  timeout: 180_000, // benchmark sweeps are genuinely slow
  headers: { 'Content-Type': 'application/json' },
})

/* -------------------------------------------------------------------------- */
/* Authentication                                                              */
/* -------------------------------------------------------------------------- */
/**
 * The session token is injected rather than imported.
 *
 * `lib/auth.js` registers these at load. Done the other way round — this
 * module importing the session store — the two would import each other, and
 * whichever happened to evaluate first would see the other half-built.
 */
let tokenProvider = () => null
let unauthorizedHandler = () => {}

export function setAuthTokenProvider(fn) {
  tokenProvider = typeof fn === 'function' ? fn : () => null
}

export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = typeof fn === 'function' ? fn : () => {}
}

http.interceptors.request.use((config) => {
  const token = tokenProvider()
  if (token && !config.headers?.Authorization) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/** An error that carries the backend's error code and per-field details. */
export class ApiError extends Error {
  constructor(message, { code, status, fields, details } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code || 'UNKNOWN'
    this.status = status ?? 0
    this.fields = fields || []
    this.details = details || null
  }

  /** Field errors keyed by field name, for inline form messages. */
  get fieldMap() {
    return Object.fromEntries(this.fields.map((f) => [f.field, f.message]))
  }
}

function normaliseError(error) {
  if (axios.isCancel?.(error) || error.code === 'ERR_CANCELED') {
    const cancelled = new ApiError('Request cancelled', { code: 'CANCELLED' })
    cancelled.cancelled = true
    return cancelled
  }

  if (error.code === 'ECONNABORTED') {
    return new ApiError('The request timed out. Try a smaller fleet or fewer iterations.', {
      code: 'TIMEOUT',
    })
  }

  if (!error.response) {
    return new ApiError(
      'Cannot reach the API. Start the backend first — run start.bat, or `uvicorn backend.main:app` from the project root.',
      { code: 'NETWORK' },
    )
  }

  const { status, data } = error.response
  const envelope = data?.error

  if (envelope) {
    return new ApiError(envelope.message || 'Request failed', {
      code: envelope.code,
      status,
      fields: envelope.details?.fields,
      details: envelope.details,
    })
  }

  // FastAPI's own shape, in case something bypasses our handlers.
  const detail = data?.detail
  const message =
    typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((d) => d.msg).join('; ')
        : `Request failed with status ${status}`
  return new ApiError(message, { code: `HTTP_${status}`, status })
}

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const normalised = normaliseError(error)
    // An expired token or a deactivated account: tell the session store, so
    // the guard sends the user to sign in with a reason instead of leaving
    // them on a page whose every request quietly fails.
    if (normalised.status === 401 && !error.config?.skipAuthRedirect) {
      unauthorizedHandler(normalised.message)
    }
    return Promise.reject(normalised)
  },
)

const get = (url, config) => http.get(url, config).then((r) => r.data)
const post = (url, body, config) => http.post(url, body, config).then((r) => r.data)
const put = (url, body, config) => http.put(url, body, config).then((r) => r.data)

const del = (url, config) => http.delete(url, config).then((r) => r.data)

export const api = {
  health: (config) => get('/api/health', config),
  root: (config) => get('/', config),

  auth: {
    // `skipAuthRedirect`: a 401 here means "those credentials are wrong",
    // not "your session ended", and must not trigger the expiry handler.
    login: (body, config) => post('/api/auth/login', body, { skipAuthRedirect: true, ...config }),
    me: (config) => get('/api/auth/me', config),
    logout: (config) => post('/api/auth/logout', null, config),
    // Ends every session for this account, including the one making the call.
    logoutEverywhere: (config) => post('/api/auth/logout-everywhere', null, config),
    changePassword: (body, config) =>
      post('/api/auth/change-password', body, { skipAuthRedirect: true, ...config }),
  },

  /**
   * Employee administration. Every one of these is ADMIN-only *on the
   * server*; hiding the page from other roles is a courtesy, not the check.
   */
  admin: {
    employees: (params, config) => get('/api/admin/employees', { params, ...config }),
    employee: (id, config) => get(`/api/admin/employees/${id}`, config),
    createEmployee: (body, config) => post('/api/admin/employees', body, config),
    updateEmployee: (id, body, config) => put(`/api/admin/employees/${id}`, body, config),
    activate: (id, config) => post(`/api/admin/employees/${id}/activate`, null, config),
    deactivate: (id, config) => post(`/api/admin/employees/${id}/deactivate`, null, config),
    resetPassword: (id, body, config) =>
      post(`/api/admin/employees/${id}/reset-password`, body, config),
    revokeSessions: (id, config) =>
      post(`/api/admin/employees/${id}/revoke-sessions`, null, config),
    deleteEmployee: (id, config) => del(`/api/admin/employees/${id}`, config),
  },

  optimization: {
    algorithms: (config) => get('/api/optimization/algorithms', config),
    registry: (config) => get('/api/optimization/registry', config),
    fleet: (params, config) => get('/api/optimization/fleet', { params, ...config }),
    optimize: (body, config) => post('/api/optimization/optimize', body, config),
    compare: (body, config) => post('/api/optimization/compare', body, config),
  },

  prediction: {
    predict: (body, config) => post('/api/prediction/predict', body, config),
    predictBatch: (body, config) => post('/api/prediction/predict/batch', body, config),
    train: (body, config) => post('/api/prediction/train', body, config),
    metrics: (config) => get('/api/prediction/metrics', config),
    featureImportance: (config) => get('/api/prediction/feature-importance', config),
    modelInfo: (config) => get('/api/prediction/model-info', config),
  },

  benchmarks: {
    run: (body, config) => post('/api/benchmarks/run', body, config),
    results: (config) => get('/api/benchmarks/results', config),
    convergence: (config) => get('/api/benchmarks/convergence', config),
    scalability: (body, config) => post('/api/benchmarks/scalability', body, config),
    metricsGuide: (config) => get('/api/benchmarks/metrics-guide', config),
  },

  regulatory: {
    ecaZones: (config) => get('/api/regulatory/eca-zones', config),
    routes: (config) => get('/api/regulatory/routes', config),
    ciiReference: (params, config) => get('/api/regulatory/cii-reference', { params, ...config }),
    rate: (body, config) => post('/api/regulatory/cii', body, config),
    seasonality: (params, config) => get('/api/regulatory/seasonality', { params, ...config }),
  },

  scenarios: {
    fuels: (config) => get('/api/scenarios/fuels', config),
    fleet: (config) => get('/api/scenarios/fleet', config),
    setFleet: (body, config) => put('/api/scenarios/fleet', body, config),
    analyze: (body, config) => post('/api/scenarios/analyze', body, config),
    compare: (body, config) => post('/api/scenarios/compare', body, config),
    shorePower: (body, config) => post('/api/scenarios/shore-power', body, config),
    transitionPlan: (body, config) => post('/api/scenarios/transition-plan', body, config),
  },
}

/**
 * Watch an optimisation converge over server-sent events.
 *
 * `EventSource` only speaks GET, which is why the streaming endpoint takes
 * query parameters rather than a body. Returns a `close` function; call it on
 * unmount or the browser keeps the connection — and the solver thread —
 * alive after the user has navigated away.
 */
export function streamOptimization(params, { onStart, onProgress, onDone, onError } = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') query.set(key, String(value))
  })

  const source = new EventSource(`${baseURL}/api/optimization/stream?${query}`)
  let settled = false

  const close = () => {
    settled = true
    source.close()
  }

  const parse = (handler) => (event) => {
    if (!handler) return
    try {
      handler(JSON.parse(event.data))
    } catch {
      // A malformed frame is not worth tearing the stream down for.
    }
  }

  source.addEventListener('start', parse(onStart))
  source.addEventListener('progress', parse(onProgress))
  source.addEventListener('done', (event) => {
    settled = true
    parse(onDone)(event)
    source.close()
  })
  source.addEventListener('error', (event) => {
    // Two different things arrive on this name: our own `error` event, which
    // carries a JSON payload, and the browser's transport error, which does
    // not. Only the latter means the connection itself failed.
    if (event.data) {
      settled = true
      parse(onError)(event)
      source.close()
      return
    }
    if (settled) return
    settled = true
    source.close()
    onError?.({ code: 'NETWORK', message: 'Lost the connection to the solver stream.' })
  })

  return close
}

export default api
