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
  (error) => Promise.reject(normaliseError(error)),
)

const get = (url, config) => http.get(url, config).then((r) => r.data)
const post = (url, body, config) => http.post(url, body, config).then((r) => r.data)
const put = (url, body, config) => http.put(url, body, config).then((r) => r.data)

export const api = {
  health: (config) => get('/api/health', config),
  root: (config) => get('/', config),

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

export default api
