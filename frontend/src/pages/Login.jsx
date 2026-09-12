/**
 * Sign-in — dual-panel layout.
 *
 * Two login modes: Administrator and Employee. Both hit the same backend
 * endpoint (`POST /api/auth/login`) and the role is determined by the
 * account, not the panel — but the visual split tells users up front that
 * there are two types of access and what each one reaches.
 *
 * The chart panel on the left is drawn from the same Natural Earth coastline
 * the application's maps use — bundled, so this screen renders identically
 * with the backend down or the venue Wi-Fi dead.
 */
import { Eye, EyeOff, Moon, Shield, Sun, User } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { Alert, cx } from '../components/ui'
import { project } from '../data/geography'
import LAND_PATH from '../data/land'
import { useTheme } from '../hooks/useTheme'
import { clearExpiryNotice, signIn, useSession, validateCredentials } from '../lib/auth'

/**
 * Ports for the chart panel.
 *
 * A short hard-coded list rather than a fetch: the sign-in screen must not
 * depend on the API being up. The authoritative registry lives server-side in
 * `backend/data/sea_routes.py` and is what every map after this point uses.
 */
const CHART_PORTS = [
  { name: 'Kandla', lat: 23.02, lon: 70.22, side: 'left' },
  { name: 'Nhava Sheva', lat: 18.95, lon: 72.95, side: 'left' },
  { name: 'Kochi', lat: 9.97, lon: 76.26, side: 'left' },
  { name: 'Chennai', lat: 13.09, lon: 80.29, side: 'right' },
  { name: 'Paradip', lat: 20.26, lon: 86.68, side: 'right' },
  { name: 'Singapore', lat: 1.26, lon: 103.83, side: 'left' },
]

/** Figures from the registry. Static here for the same reason as the ports. */
const SCALE = [
  { value: '20', label: 'Vessels' },
  { value: '16', label: 'Trade lanes' },
  { value: '4', label: 'Solvers' },
]

// Red Sea to the Malacca Strait, at roughly the panel's own aspect so the
// crop is gentle. Framed so India and the Bay of Bengal fall in the right-hand
// half, clear of the copy.
const VIEW_BOX = '213 50 75 68'

/* -------------------------------------------------------------------------- */
/* Chart panel                                                                 */
/* -------------------------------------------------------------------------- */
function ChartPanel() {
  const graticule = []
  for (let lon = 30; lon <= 150; lon += 10) {
    graticule.push(<line key={`v${lon}`} x1={lon + 180} y1={0} x2={lon + 180} y2={180} />)
  }
  for (let lat = -30; lat <= 50; lat += 10) {
    graticule.push(<line key={`h${lat}`} x1={0} y1={90 - lat} x2={360} y2={90 - lat} />)
  }

  return (
    <svg
      viewBox={VIEW_BOX}
      preserveAspectRatio="xMidYMid slice"
      className="absolute inset-0 h-full w-full"
      aria-hidden
    >
      <rect x={0} y={0} width={360} height={180} fill="#08192a" />
      <g stroke="#153048" strokeWidth={0.09}>
        {graticule}
      </g>
      {/* The equator, as a chart marks it. */}
      <line x1={0} y1={90} x2={360} y2={90} stroke="#20486a" strokeWidth={0.14} />
      <text x={215} y={89} fontSize={1.3} fill="#3a678a" fontFamily="ui-monospace, monospace">
        0°
      </text>

      <path d={LAND_PATH} fill="#16304a" stroke="#2d6288" strokeWidth={0.16} strokeLinejoin="round" />

      {CHART_PORTS.map(({ name, lat, lon, side }) => {
        const [x, y] = project([lat, lon])
        return (
          <g key={name}>
            <path
              d={`M${x - 0.75} ${y} L${x + 0.75} ${y} M${x} ${y - 0.75} L${x} ${y + 0.75}`}
              stroke="#3f7799"
              strokeWidth={0.11}
            />
            <circle cx={x} cy={y} r={0.3} fill="#6ea6c4" />
            <text
              x={side === 'right' ? x + 1.1 : x - 1.1}
              y={y + 0.42}
              textAnchor={side === 'right' ? 'start' : 'end'}
              fontSize={1.25}
              fill="#5f92b3"
              letterSpacing="0.1"
              fontFamily="ui-monospace, monospace"
            >
              {name.toUpperCase()}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

/**
 * A compass rose. The earlier hexagon read as a water droplet at 28 px, which
 * is the wrong industry.
 */
function Mark({ className }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <circle cx="16" cy="16" r="12.5" fill="none" stroke="currentColor" strokeWidth="1.4" opacity="0.45" />
      <path d="M16 2.5 19 16l-3 13.5L13 16z" fill="currentColor" />
      <path d="M2.5 16 16 13l13.5 3L16 19z" fill="currentColor" opacity="0.5" />
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Role selector tabs                                                          */
/* -------------------------------------------------------------------------- */
const ROLES = [
  {
    key: 'admin',
    label: 'Administrator',
    icon: Shield,
    description: 'Full access — manage employees, fleet operations and system settings.',
    accent: 'violet',
  },
  {
    key: 'employee',
    label: 'Employee',
    icon: User,
    description: 'Voyage planning, fleet optimisation and compliance reporting.',
    accent: 'primary',
  },
]

function RoleTab({ role, active, onClick }) {
  const Icon = role.icon
  const isAdmin = role.key === 'admin'

  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'group flex flex-1 flex-col items-center gap-2 rounded-xl border-2 px-4 py-4 text-center transition-all',
        active
          ? isAdmin
            ? 'border-violet-500 bg-violet-50 dark:border-violet-400 dark:bg-violet-950/30'
            : 'border-primary-500 bg-primary-50 dark:border-primary-400 dark:bg-primary-950/30'
          : 'border-[rgb(var(--border-subtle))] hover:border-[rgb(var(--border-strong))] hover:bg-[rgb(var(--surface-sunken))]',
      )}
    >
      <span
        className={cx(
          'flex h-10 w-10 items-center justify-center rounded-lg transition-colors',
          active
            ? isAdmin
              ? 'bg-violet-500 text-white dark:bg-violet-500'
              : 'bg-primary-600 text-white dark:bg-primary-500'
            : 'bg-[rgb(var(--surface-sunken))] text-[rgb(var(--text-muted))] group-hover:text-[rgb(var(--text-primary))]',
        )}
      >
        <Icon size={20} />
      </span>
      <span
        className={cx(
          'text-sm font-semibold transition-colors',
          active
            ? isAdmin
              ? 'text-violet-700 dark:text-violet-300'
              : 'text-primary-700 dark:text-primary-300'
            : 'text-[rgb(var(--text-muted))]',
        )}
      >
        {role.label}
      </span>
      <span
        className={cx(
          'text-[0.7rem] leading-snug transition-colors',
          active ? 'text-[rgb(var(--text-body))]' : 'text-[rgb(var(--text-muted))]',
        )}
      >
        {role.description}
      </span>
    </button>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */
export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const [theme, toggleTheme] = useTheme()

  const [loginRole, setLoginRole] = useState('admin')
  const [employeeId, setEmployeeId] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [showPassword, setShowPassword] = useState(false)
  const [errors, setErrors] = useState({})
  const [ownNotice, setOwnNotice] = useState(null)
  const [failure, setFailure] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [capsLock, setCapsLock] = useState(false)
  // Seconds left on a server-side lockout. Counts down so the user has a
  // number to wait out instead of retrying into a wall.
  const [lockedFor, setLockedFor] = useState(0)

  const employeeIdRef = useRef(null)
  const passwordRef = useRef(null)

  // If a session ended mid-visit — token expired, or the account was
  // deactivated — say so rather than leaving the user wondering why they are
  // back at the sign-in screen. It lives in the session store, so it survives
  // the redirect that brought them here.
  const { expiryNotice } = useSession()
  const notice = ownNotice ?? expiryNotice ?? null

  const dismissNotice = () => {
    setOwnNotice(null)
    clearExpiryNotice()
  }

  // Where the user was heading before the gate sent them here.
  const destination = location.state?.from?.pathname ?? '/'

  // Tick the lockout down. One interval, started when the lock appears and
  // cleared when it clears, so a user who waits it out watches the button
  // re-enable itself rather than guessing. The effect depends on the boolean,
  // not the number, or it would tear down and rebuild the interval every
  // second — and the functional update means it never needs to read the count.
  const isLocked = lockedFor > 0
  useEffect(() => {
    if (!isLocked) return undefined
    const id = window.setInterval(() => setLockedFor((s) => Math.max(0, s - 1)), 1000)
    return () => window.clearInterval(id)
  }, [isLocked])

  /** Warn about Caps Lock — the commonest reason a correct password fails. */
  const trackCapsLock = (event) => {
    try {
      setCapsLock(event.getModifierState?.('CapsLock') ?? false)
    } catch {
      /* not every browser reports modifier state on every event */
    }
  }

  // Clear form state when switching roles, so a half-typed admin ID does not
  // linger in the employee panel.
  const switchRole = (key) => {
    if (key === loginRole) return
    setLoginRole(key)
    setEmployeeId('')
    setPassword('')
    setErrors({})
    setFailure(null)
    setShowPassword(false)
    setCapsLock(false)
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (submitting) return

    const found = validateCredentials({ employeeId, password })
    setErrors(found)
    dismissNotice()
    setFailure(null)

    if (Object.keys(found).length) {
      // Send focus to the first problem so a keyboard user is not hunting.
      ;(found.employeeId ? employeeIdRef : passwordRef).current?.focus()
      return
    }

    setSubmitting(true)
    try {
      const result = await signIn({ employeeId, password, remember })
      if (result.persisted === false) {
        // Honour the box or say why not, rather than quietly dropping it.
        setOwnNotice('Signed in, but this browser would not let us remember you.')
      }
      navigate(destination, { replace: true })
    } catch (error) {
      // The server's message, verbatim. For a wrong password and an unknown
      // Employee ID it is deliberately identical — see backend/auth/api.py.
      setFailure(error?.message || 'Sign-in failed. Try again.')
      if (error?.code === 'RATE_LIMITED') {
        setLockedFor(Number(error.details?.retry_after_seconds) || 60)
      }
      setPassword('')
      passwordRef.current?.focus()
    } finally {
      setSubmitting(false)
    }
  }

  const busy = submitting || isLocked
  const isAdmin = loginRole === 'admin'

  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_33rem] xl:grid-cols-[1fr_36rem]">
      {/* ---------------------------------------------------------------- */}
      {/* Chart panel                                                       */}
      {/* ---------------------------------------------------------------- */}
      <aside className="relative hidden overflow-hidden bg-[#0b1c2e] lg:flex lg:flex-col">
        <ChartPanel />
        {/* A flat scrim, not a decorative gradient: the type has to stay
            readable over coastline wherever the panel is cropped. */}
        <div
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(96deg, rgba(6,17,29,0.96) 0%, rgba(6,17,29,0.9) 38%, rgba(6,17,29,0.55) 68%, rgba(6,17,29,0.3) 100%)',
          }}
        />

        <div className="relative flex h-full flex-col justify-between p-10 xl:p-12">
          <div className="flex items-center gap-3 text-slate-100">
            <Mark className="h-7 w-7 text-primary-400" />
            <span className="text-[0.78rem] font-semibold uppercase tracking-[0.18em]">
              Fleet Fuel Optimization
            </span>
          </div>

          <div className="max-w-lg">
            <p className="font-mono text-[0.68rem] uppercase tracking-[0.22em] text-primary-400/80">
              Voyage planning platform
            </p>
            <h1 className="mt-4 max-w-[19ch] text-[1.4rem] font-semibold leading-[1.35] tracking-tight text-white xl:text-[1.6rem]">
              Intelligent voyage planning for fuel-efficient maritime operations.
            </h1>
            <p className="mt-4 max-w-sm text-[0.82rem] leading-relaxed text-slate-400">
              Multi-objective deployment planning across the Indian trade lanes — speed, routing,
              bunker selection and shore power solved together against fuel, emissions and cost.
            </p>

            <dl className="mt-8 flex max-w-sm items-stretch border-t border-white/10 pt-5">
              {SCALE.map(({ value, label }, index) => (
                <div
                  key={label}
                  className={cx('flex-1', index > 0 && 'border-l border-white/10 pl-5', index === 0 && 'pr-5')}
                >
                  <dt className="text-[0.68rem] uppercase tracking-[0.14em] text-slate-500">
                    {label}
                  </dt>
                  <dd className="numeric mt-1 text-lg font-semibold text-slate-200">{value}</dd>
                </div>
              ))}
            </dl>
          </div>

          <p className="font-mono text-[0.68rem] tracking-wide text-slate-600">
            Indian Ocean · Arabian Sea · Bay of Bengal · Malacca Strait
          </p>
        </div>
      </aside>

      {/* ---------------------------------------------------------------- */}
      {/* Form                                                              */}
      {/* ---------------------------------------------------------------- */}
      <main
        className="relative flex flex-col justify-center px-6 py-12 sm:px-10 lg:px-14"
        style={{ backgroundColor: 'rgb(var(--surface-card))' }}
      >
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          className="absolute right-5 top-5 rounded-md p-2 transition-colors hover:bg-[rgb(var(--surface-sunken))]"
        >
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>

        <div className="mx-auto w-full max-w-[28rem]">
          {/* Brand block, for the widths where the chart panel is not shown. */}
          <div className="mb-9 flex items-start gap-3 lg:hidden">
            <Mark className="mt-0.5 h-7 w-7 shrink-0 text-primary-600 dark:text-primary-400" />
            <div>
              <p className="text-[0.78rem] font-semibold uppercase tracking-[0.16em]">
                Fleet Fuel Optimization
              </p>
              <p className="text-faint mt-0.5 text-xs">
                Intelligent voyage planning for fuel-efficient maritime operations.
              </p>
            </div>
          </div>

          <header className="mb-6">
            <h2 className="text-xl font-semibold tracking-tight">Sign in to your account</h2>
            <p className="text-body mt-1.5 text-sm">
              Select your role and enter your credentials.
            </p>
          </header>

          {/* ---- Role selector ---- */}
          <div className="mb-6 flex gap-3" role="radiogroup" aria-label="Login type">
            {ROLES.map((role) => (
              <RoleTab
                key={role.key}
                role={role}
                active={loginRole === role.key}
                onClick={() => switchRole(role.key)}
              />
            ))}
          </div>

          {notice && (
            <Alert tone="warning" className="mb-5" onDismiss={dismissNotice}>
              {notice}
            </Alert>
          )}

          {failure && (
            <Alert tone="error" className="mb-5" onDismiss={() => setFailure(null)}>
              {failure}
            </Alert>
          )}

          {/* ---- Login form ---- */}
          <div
            className={cx(
              'rounded-xl border-2 p-5 transition-colors',
              isAdmin
                ? 'border-violet-200 dark:border-violet-800/50'
                : 'border-primary-200 dark:border-primary-800/50',
            )}
          >
            <div className="mb-4 flex items-center gap-2.5">
              {isAdmin ? (
                <Shield size={18} className="text-violet-600 dark:text-violet-400" />
              ) : (
                <User size={18} className="text-primary-600 dark:text-primary-400" />
              )}
              <h3
                className={cx(
                  'text-sm font-semibold',
                  isAdmin
                    ? 'text-violet-700 dark:text-violet-300'
                    : 'text-primary-700 dark:text-primary-300',
                )}
              >
                {isAdmin ? 'Administrator Login' : 'Employee Login'}
              </h3>
            </div>

            <form onSubmit={handleSubmit} noValidate className="space-y-4">
              <div>
                <label htmlFor="login-employee-id" className="auth-label">
                  {isAdmin ? 'Admin ID' : 'Employee ID'}
                </label>
                <input
                  id="login-employee-id"
                  ref={employeeIdRef}
                  type="text"
                  autoComplete="username"
                  autoFocus
                  spellCheck={false}
                  autoCapitalize="characters"
                  // Administrators are issued ADMIN-prefixed IDs and staff
                  // EMP-prefixed ones, each numbered from 001 — see
                  // `manage.py seed` and migration 0005, which is what put an
                  // existing database onto that convention.
                  placeholder={isAdmin ? 'ADMIN001' : 'EMP001'}
                  value={employeeId}
                  disabled={busy}
                  aria-invalid={errors.employeeId ? 'true' : undefined}
                  aria-describedby={errors.employeeId ? 'login-employee-id-error' : undefined}
                  onChange={(event) => {
                    setEmployeeId(event.target.value)
                    if (errors.employeeId) setErrors((e) => ({ ...e, employeeId: undefined }))
                  }}
                  className="field-control"
                />
                {errors.employeeId && (
                  <p id="login-employee-id-error" className="auth-error">
                    {errors.employeeId}
                  </p>
                )}
              </div>

              <div>
                <div className="flex items-baseline justify-between gap-3">
                  <label htmlFor="login-password" className="auth-label">
                    Password
                  </label>
                  <button
                    type="button"
                    onClick={() =>
                      setOwnNotice(
                        'Passwords are reset by an administrator from the Employees page — there is no self-service reset. Ask them to set a new one for your Employee ID.',
                      )
                    }
                    className="text-xs text-primary-700 underline-offset-2 hover:underline dark:text-primary-400"
                  >
                    Forgot password?
                  </button>
                </div>
                <div className="relative">
                  <input
                    id="login-password"
                    ref={passwordRef}
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    placeholder="••••••••"
                    value={password}
                    disabled={busy}
                    aria-invalid={errors.password ? 'true' : undefined}
                    aria-describedby={
                      [errors.password && 'login-password-error', capsLock && 'login-capslock']
                        .filter(Boolean)
                        .join(' ') || undefined
                    }
                    onKeyDown={trackCapsLock}
                    onKeyUp={trackCapsLock}
                    onBlur={() => setCapsLock(false)}
                    onChange={(event) => {
                      setPassword(event.target.value)
                      if (errors.password) setErrors((e) => ({ ...e, password: undefined }))
                    }}
                    className="field-control pr-11"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    aria-pressed={showPassword}
                    className="text-faint absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-lg transition-colors hover:text-[rgb(var(--text-primary))]"
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                {errors.password && (
                  <p id="login-password-error" className="auth-error">
                    {errors.password}
                  </p>
                )}
                {capsLock && !errors.password && (
                  <p
                    id="login-capslock"
                    role="status"
                    className="mt-1.5 text-xs text-amber-600 dark:text-amber-400"
                  >
                    Caps Lock is on.
                  </p>
                )}
              </div>

              <label className="flex cursor-pointer select-none items-center gap-2.5 text-sm">
                <input
                  type="checkbox"
                  checked={remember}
                  disabled={busy}
                  onChange={(event) => setRemember(event.target.checked)}
                  className="h-4 w-4 cursor-pointer rounded border-[rgb(var(--border-strong))] accent-primary-600"
                />
                <span className="text-body">Keep me signed in on this device</span>
              </label>

              <button
                type="submit"
                disabled={busy}
                className={cx(
                  'auth-button-primary',
                  isAdmin && 'bg-violet-600 hover:bg-violet-700 dark:bg-violet-600 dark:hover:bg-violet-500',
                )}
              >
                {submitting
                  ? 'Signing in…'
                  : lockedFor > 0
                    ? `Try again in ${lockedFor}s`
                    : isAdmin
                      ? 'Sign in as Administrator'
                      : 'Sign in as Employee'}
              </button>
            </form>
          </div>

          <p className="text-faint mt-6 text-xs leading-relaxed">
            Accounts are issued by your fleet administrator. Sign-in is checked against the
            account server; passwords are stored only as bcrypt hashes, and the session on this
            device expires after 12 hours.
          </p>
        </div>
      </main>
    </div>
  )
}
