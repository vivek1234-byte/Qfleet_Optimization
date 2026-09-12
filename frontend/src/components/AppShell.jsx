/**
 * Application shell: horizontal top navigation, mobile drawer, theme toggle,
 * backend status. Sidebar eliminated — nav items run across the top bar so no
 * vertical space is wasted.
 *
 * The health indicator polls rather than checking once, because the single
 * most common failure at a demo is the backend dying quietly while the browser
 * still shows the last good screen.
 */
import { LogOut, Menu, Moon, Sun, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'

import { usePolling } from '../hooks/useApi'
import { useTheme } from '../hooks/useTheme'
import api from '../lib/api'
import { signOut, useSession } from '../lib/auth'
import { navItemsFor } from '../lib/nav'
import SeaStateAlerts from './SeaStateAlerts'
import { cx } from './ui'

function BackendStatus() {
  const { data, error } = usePolling((signal) => api.health({ signal }), 20_000)

  const state = error
    ? { tone: 'bg-rose-500', label: 'API offline', detail: error.message }
    : !data
      ? { tone: 'bg-slate-400', label: 'Checking…', detail: '' }
      : data.status === 'healthy'
        ? { tone: 'bg-eco-500', label: 'API healthy', detail: `v${data.version}` }
        : {
            tone: 'bg-amber-500',
            label: 'API degraded',
            detail: Object.entries(data.checks || {})
              .filter(([, check]) => !check.ok)
              .map(([name, check]) => `${name}: ${check.detail}`)
              .join(' · '),
          }

  return (
    <div className="flex items-center gap-1.5 text-[0.7rem]" title={state.detail || state.label}>
      <span className={cx('h-2 w-2 shrink-0 rounded-full', state.tone)} aria-hidden />
      <span className="hidden truncate text-slate-400 sm:inline">{state.label}</span>
    </div>
  )
}

/** Who is signed in, and the way out. */
function HeaderAccount() {
  const { session } = useSession()
  const navigate = useNavigate()
  if (!session) return null

  const initials =
    (session.name ?? '')
      .split(' ')
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join('') || '?'

  return (
    <div className="flex items-center gap-2">
      <span
        className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary-600 text-[0.7rem] font-semibold text-white"
        aria-hidden
      >
        {initials}
      </span>
      <span className="hidden items-center gap-1.5 text-xs sm:flex">
        <span className="font-medium">{session.name}</span>
        <span className="text-faint">·</span>
        <span className="text-faint">
          {session.role === 'ADMIN' ? 'Admin' : 'Employee'}
        </span>
      </span>
      <button
        type="button"
        onClick={() => {
          signOut()
          navigate('/login', { replace: true })
        }}
        aria-label="Sign out"
        title="Sign out"
        className="shrink-0 rounded-lg p-1.5 transition-colors hover:bg-[rgb(var(--surface-sunken))]"
      >
        <LogOut size={16} />
      </button>
    </div>
  )
}

const NAV_LINK = (isActive) =>
  cx(
    'relative flex items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors',
    isActive
      ? 'text-primary-500'
      : 'text-faint hover:text-[rgb(var(--text-primary))]',
  )

export default function AppShell({ children }) {
  const [theme, toggleTheme] = useTheme()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const { session } = useSession()

  // The whole session, not just the role: the nav now also filters on the
  // modules this individual was granted.
  const items = navItemsFor(session)

  useEffect(() => {
    document.body.style.overflow = mobileOpen ? 'hidden' : ''
    return () => {
      document.body.style.overflow = ''
    }
  }, [mobileOpen])

  // Close drawer on navigation
  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  useEffect(() => {
    const onKeyDown = (event) => event.key === 'Escape' && setMobileOpen(false)
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  // The simulator wants the full viewport; every other page reads better with
  // the usual page padding and a max width.
  const isWide = location.pathname.startsWith('/simulator')

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-primary-600 focus:px-4 focus:py-2 focus:text-white"
      >
        Skip to content
      </a>

      {/* ── Top bar ─────────────────────────────────────────────── */}
      <header
        className="surface sticky top-0 z-30 border-b backdrop-blur"
        style={{ backgroundColor: 'rgb(var(--surface-card) / 0.9)' }}
      >
        {/* Primary row: logo · status · theme · account */}
        <div className="flex items-center gap-3 px-4 py-2 lg:px-6">
          {/* Mobile hamburger */}
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            aria-expanded={mobileOpen}
            className="-ml-1 rounded-lg p-2 transition-colors hover:bg-[rgb(var(--surface-sunken))] lg:hidden"
          >
            <Menu size={20} />
          </button>

          {/* Compact wordmark */}
          <div className="flex items-center gap-2.5">
            <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-primary-500 to-eco-500 shadow-md">
              <svg viewBox="0 0 32 32" className="h-[1.1rem] w-[1.1rem]" aria-hidden>
                <path
                  d="M16 5.5 21 14v6.2l-5 2.4-5-2.4V14z"
                  fill="none"
                  stroke="#fff"
                  strokeWidth="2"
                  strokeLinejoin="round"
                />
                <circle cx="16" cy="14.5" r="2" fill="#fff" />
              </svg>
            </div>
            <span className="text-sm font-semibold">QFleet</span>
          </div>

          {/* Spacer */}
          <div className="min-w-0 flex-1" />

          {/* Backend health dot */}
          <BackendStatus />

          {/* Sea-state warning. Renders nothing when no lane is flagged, so
              the header stays quiet on a calm month. */}
          <SeaStateAlerts />

          {/* Theme toggle */}
          <button
            type="button"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            className="rounded-lg p-2 transition-colors hover:bg-[rgb(var(--surface-sunken))]"
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>

          <div className="h-5 w-px bg-[rgb(var(--border-subtle))]" aria-hidden />

          {/* Account + sign out */}
          <HeaderAccount />
        </div>

        {/* Navigation row — desktop horizontal nav */}
        <nav
          className="hidden overflow-x-auto border-t px-4 lg:flex lg:px-6"
          style={{ borderColor: 'rgb(var(--border-subtle) / 0.5)' }}
          aria-label="Main"
        >
          <div className="flex items-center gap-1 py-1">
            {items.map(({ name, path, icon: Icon, end }) => (
              <NavLink key={path} to={path} end={end} className={({ isActive }) => NAV_LINK(isActive)}>
                {({ isActive }) => (
                  <>
                    <Icon size={14} className="shrink-0" aria-hidden />
                    {name}
                    {isActive && (
                      <span
                        className="absolute inset-x-2.5 -bottom-1 h-0.5 rounded-full bg-primary-500"
                        aria-hidden
                      />
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        </nav>
      </header>

      {/* ── Mobile drawer ───────────────────────────────────────── */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="animate-fade-in absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-ink-950 p-4 shadow-pop">
            {/* Drawer header */}
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-3 px-2 py-1">
                <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-primary-500 to-eco-500 shadow-lg">
                  <svg viewBox="0 0 32 32" className="h-5 w-5" aria-hidden>
                    <path
                      d="M16 5.5 21 14v6.2l-5 2.4-5-2.4V14z"
                      fill="none"
                      stroke="#fff"
                      strokeWidth="2"
                      strokeLinejoin="round"
                    />
                    <circle cx="16" cy="14.5" r="2" fill="#fff" />
                  </svg>
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-white">QFleet</p>
                  <p className="truncate text-xs text-slate-400">Quantum Green Fleet</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setMobileOpen(false)}
                aria-label="Close navigation"
                className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-white/5 hover:text-white"
              >
                <X size={18} />
              </button>
            </div>

            {/* Drawer nav — full labels + blurbs */}
            <nav className="space-y-1 overflow-y-auto" aria-label="Main">
              {items.map(({ name, path, icon: Icon, end, blurb }) => (
                <NavLink
                  key={path}
                  to={path}
                  end={end}
                  className={({ isActive }) =>
                    cx(
                      'flex items-start gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-primary-600 text-white shadow-sm'
                        : 'text-slate-400 hover:bg-white/5 hover:text-white',
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon size={18} className="mt-0.5 shrink-0" aria-hidden />
                      <span className="min-w-0">
                        <span className="block truncate">{name}</span>
                        <span
                          className={cx(
                            'block truncate text-xs font-normal',
                            isActive ? 'text-primary-100' : 'text-slate-600',
                          )}
                        >
                          {blurb}
                        </span>
                      </span>
                    </>
                  )}
                </NavLink>
              ))}
            </nav>

            <div className="mt-4 space-y-2 border-t border-white/10 px-2 pt-3">
              <a
                href="/docs"
                target="_blank"
                rel="noreferrer"
                className="block text-xs text-slate-500 transition-colors hover:text-slate-300"
              >
                API documentation ↗
              </a>
            </div>
          </aside>
        </div>
      )}

      {/* ── Main content — full width ───────────────────────────── */}
      <main
        id="main-content"
        className={cx('flex-1', isWide ? 'p-3 lg:p-5' : 'px-4 py-4 lg:px-8 lg:py-6')}
      >
        <div className={cx('mx-auto w-full', isWide ? 'max-w-none' : 'max-w-7xl')}>{children}</div>
      </main>

      {!isWide && (
        <footer className="text-faint px-4 py-3 text-center text-xs lg:px-8">QFleet</footer>
      )}
    </div>
  )
}
