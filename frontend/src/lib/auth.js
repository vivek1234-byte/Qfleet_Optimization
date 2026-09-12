/**
 * The sign-in gate.
 *
 * Backed by a real account server: `POST /api/auth/login` checks an Employee
 * ID and password against the `employees` table (bcrypt hashes, never plain
 * text) and returns a signed token. This module holds that token, exposes who
 * is signed in, and revalidates on load.
 *
 * Three things worth knowing before changing it:
 *
 * 1. **The token is the session.** Everything below `/login` is gated on
 *    having one, and `lib/api.js` sends it as `Authorization: Bearer …`.
 * 2. **The role in the session is for presentation only.** It decides whether
 *    the Admin link appears. It decides nothing about what the API will
 *    allow — `require_admin` on the backend does that, and editing the stored
 *    role in devtools gets you a link that 403s.
 * 3. **Stored tokens are revalidated, not trusted.** On load the token is
 *    checked against `GET /api/auth/me` before the dashboard renders, which
 *    is how a deactivated account is turned away on the next page view rather
 *    than whenever its token expires.
 *
 * Persistence follows the "remember me" box: localStorage when ticked so the
 * session outlives the tab, sessionStorage when not.
 */
import { useSyncExternalStore } from 'react'

import api, { ApiError, setAuthTokenProvider, setUnauthorizedHandler } from './api'

const STORAGE_KEY = 'qfleet.session'

const listeners = new Set()

function safeStorage(kind) {
  // Private browsing and locked-down profiles throw on access rather than
  // returning null, so every touch is guarded.
  try {
    return typeof window === 'undefined' ? null : window[kind]
  } catch {
    return null
  }
}

function readStored() {
  for (const kind of ['localStorage', 'sessionStorage']) {
    const store = safeStorage(kind)
    if (!store) continue
    try {
      const raw = store.getItem(STORAGE_KEY)
      if (!raw) continue
      const parsed = JSON.parse(raw)
      if (!parsed?.token || !parsed?.employee) continue
      // The server is the authority on expiry; this only avoids sending a
      // token we already know is stale.
      if (parsed.expiresAt && Date.parse(parsed.expiresAt) <= Date.now()) {
        store.removeItem(STORAGE_KEY)
        continue
      }
      return parsed
    } catch {
      // Corrupt entry: drop it rather than trapping the user on the login
      // screen with an error they cannot clear.
      try {
        store.removeItem(STORAGE_KEY)
      } catch {
        /* nothing further to try */
      }
    }
  }
  return null
}

function persist(session, remember) {
  const target = safeStorage(remember ? 'localStorage' : 'sessionStorage')
  const other = safeStorage(remember ? 'sessionStorage' : 'localStorage')
  try {
    other?.removeItem(STORAGE_KEY)
  } catch {
    /* the other store is not writable; nothing to clean up */
  }
  try {
    target?.setItem(STORAGE_KEY, JSON.stringify(session))
    return true
  } catch {
    // Quota or a blocked store. The session still works for this page view.
    return false
  }
}

function clearStored() {
  for (const kind of ['localStorage', 'sessionStorage']) {
    try {
      safeStorage(kind)?.removeItem(STORAGE_KEY)
    } catch {
      /* already gone, or the store is unavailable */
    }
  }
}

/**
 * Shape a session from the server's login response.
 *
 * `role` and `name` are copies for the UI to render. The authoritative values
 * are the ones the server attaches to the token on every request.
 */
function toSession({ access_token, expires_at, employee }, remember) {
  return {
    token: access_token,
    expiresAt: expires_at,
    remember,
    employee,
    // Convenience aliases, so components read `session.name` rather than
    // reaching into `session.employee` everywhere.
    name: employee.full_name,
    employeeId: employee.employee_id,
    role: employee.role,
    department: employee.department,
    email: employee.email,
    // Which modules this person may open, resolved by the server (an
    // administrator's full catalogue, an explicit grant, or the default set).
    // The client never recomputes that rule, so the navigation and the API
    // cannot disagree about who may see what.
    permissions: employee.permissions ?? [],
  }
}

// Hydrated synchronously at module load, so a returning user never sees the
// login screen flash before the redirect. `status` starts as 'checking' when
// there is a stored token: the guard waits for revalidation rather than
// rendering the dashboard against a token the server may have stopped
// honouring.
const _restored = readStored()
let state = {
  session: _restored,
  status: _restored ? 'checking' : 'anonymous',
}

function emit() {
  listeners.forEach((listener) => listener())
}

function setState(next) {
  state = { ...state, ...next }
  emit()
}

/** The current bearer token, for `lib/api.js`. */
export function getToken() {
  return state.session?.token ?? null
}

/**
 * Sign in against the API.
 *
 * Throws the `ApiError` from the server on failure so the form can show the
 * server's own message — which, for a bad Employee ID or a bad password, is
 * deliberately the same message.
 */
export async function signIn({ employeeId, password, remember = false }) {
  const data = await api.auth.login({
    employee_id: String(employeeId ?? '').trim(),
    password,
  })
  const session = toSession(data, remember)
  const persisted = persist(session, remember)
  setState({ session, status: 'authenticated' })
  return { persisted, session }
}

/**
 * Drop the session.
 *
 * The local state goes first and unconditionally: a user who clicks sign out
 * must be signed out even if the network call fails. The server call is
 * best-effort — tokens are stateless, so it logs the event rather than
 * revoking anything.
 */
export function signOut() {
  const token = state.session?.token
  clearStored()
  setState({ session: null, status: 'anonymous' })
  if (token) {
    api.auth.logout({ headers: { Authorization: `Bearer ${token}` } }).catch(() => {
      /* already signed out locally; nothing useful to do */
    })
  }
}

/**
 * Called by the api client when any request comes back 401.
 *
 * The token has expired or the account has been deactivated mid-session.
 * Clearing the session sends the guard to the login screen with the message
 * rather than leaving the user clicking a dashboard that quietly fails.
 */
export function sessionExpired(message) {
  if (!state.session) return
  clearStored()
  setState({ session: null, status: 'anonymous', expiryNotice: message || null })
}

/**
 * Clear the "your session ended" message.
 *
 * Read through `useSession().expiryNotice` and cleared here, rather than
 * consumed during render: a store write inside a render pass is the kind of
 * thing that works until it is rendered twice.
 */
export function clearExpiryNotice() {
  if (state.expiryNotice) setState({ expiryNotice: null })
}

/**
 * Revalidate a stored token against the server.
 *
 * Runs once at startup. Anything other than a definite rejection leaves the
 * session in place: if the backend is simply down, signing the user out would
 * be the wrong call — they would not be able to sign back in either.
 */
export async function revalidate() {
  if (!state.session) {
    setState({ status: 'anonymous' })
    return null
  }
  try {
    const data = await api.auth.me({ skipAuthRedirect: true })
    const refreshed = {
      ...state.session,
      employee: data,
      name: data.full_name,
      employeeId: data.employee_id,
      role: data.role,
      department: data.department,
      email: data.email,
    }
    persist(refreshed, state.session.remember)
    setState({ session: refreshed, status: 'authenticated' })
    return refreshed
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      clearStored()
      // Carry the server's reason to the login screen. Without this a
      // revoked or expired session lands on /login with no explanation,
      // which reads as the app having logged you out at random.
      setState({ session: null, status: 'anonymous', expiryNotice: error.message })
      return null
    }
    // Network or server trouble: keep the session and let the pages show
    // their own error states.
    setState({ status: 'authenticated' })
    return state.session
  }
}

// Hand the api client the two things it needs from the session: the token to
// attach, and somewhere to report a 401.
setAuthTokenProvider(getToken)
setUnauthorizedHandler(sessionExpired)

const subscribe = (listener) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

const getSnapshot = () => state

/** `{ session, status }` — session is null when signed out. */
export function useSession() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

/** True when the signed-in employee is an administrator. Presentation only. */
export function useIsAdmin() {
  const { session } = useSession()
  return session?.role === 'ADMIN'
}

/* -------------------------------------------------------------------------- */
/* Validation                                                                  */
/* -------------------------------------------------------------------------- */
/**
 * Client-side checks are for catching an empty box before a round trip.
 *
 * Deliberately no format rule on the Employee ID beyond "not empty": the
 * server does not tell you whether an ID exists, and a client-side "that is
 * not a valid Employee ID" would give away the same thing for free.
 */
export function validateCredentials({ employeeId, password }) {
  const errors = {}
  const trimmed = String(employeeId ?? '').trim()

  if (!trimmed) errors.employeeId = 'Enter your Employee ID.'
  else if (trimmed.length > 64) errors.employeeId = 'That Employee ID is too long.'

  if (!password) errors.password = 'Enter your password.'

  return errors
}
