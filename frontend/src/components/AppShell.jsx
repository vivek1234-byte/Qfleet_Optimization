/**
 * Application shell: sidebar, mobile drawer, theme toggle, backend status.
 *
 * The health indicator polls rather than checking once, because the single
 * most common failure at a demo is the backend dying quietly while the browser
 * still shows the last good screen.
 */
import { LogOut, Menu, Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'

import { usePolling } from '../hooks/useApi'
import { useTheme } from '../hooks/useTheme'
import api from '../lib/api'
import { signOut, useSession } from '../lib/auth'
import { NAV_ITEMS, navItemsFor } from '../lib/nav'
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
    <div className="flex items-center gap-2 text-xs" title={state.detail || state.label}>
      <span className={cx('h-2 w-2 shrink-0 rounded-full', state.tone)} aria-hidden />
      <span className="truncate text-slate-400">{state.label}</span>
      {state.detail && <span className="truncate text-slate-600">{state.detail}</span>}
    </div>
  )
}

/** Who is signed in, and the way out. */
function AccountBlock() {
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
    <div className="flex items-center gap-2.5">
      <span
        className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary-600 text-[0.7rem] font-semibold text-white"
        aria-hidden
      >
        {initials}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-medium text-slate-200">{session.name}</span>
        {/* Employee ID and role — how a person is identified in an operations
            room, and the two facts that decide what they can do. */}
        <span className="block truncate text-[0.68rem] text-slate-500">
          {[session.employeeId, session.role === 'ADMIN' ? 'Administrator' : 'Employee']
            .filter(Boolean)
            .join(' · ') || 'Signed in'}
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
        className="shrink-0 rounded-md p-1.5 text-slate-500 transition-colors hover:bg-white/5 hover:text-slate-200"
      >
        <LogOut size={15} />
      </button>
    </div>
  )
}

function Wordmark() {
  return (
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
  )
}

function SidebarContent({ onNavigate }) {
  const { session } = useSession()
  // Role-gated items. This decides what is *shown*; the API decides what is
  // allowed. See lib/nav.js.
  const items = navItemsFor(session?.role)

  return (
    <>
      <Wordmark />
      <nav className="mt-7 flex-1 space-y-1" aria-label="Main">
        {items.map(({ name, path, icon: Icon, end, blurb }) => (
          <NavLink
            key={path}
            to={path}
            end={end}
            onClick={onNavigate}
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

      <div className="mt-auto space-y-3 border-t border-white/10 px-2 pt-4">
        <AccountBlock />
        <BackendStatus />
        <a
          href="/docs"
          target="_blank"
          rel="noreferrer"
          className="block text-xs text-slate-500 transition-colors hover:text-slate-300"
        >
          API documentation ↗
        </a>
      </div>
    </>
  )
}

export default function AppShell({ children }) {
  const [theme, toggleTheme] = useTheme()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()

  useEffect(() => {
    document.body.style.overflow = mobileOpen ? 'hidden' : ''
    return () => {
      document.body.style.overflow = ''
    }
  }, [mobileOpen])

  useEffect(() => {
    const onKeyDown = (event) => event.key === 'Escape' && setMobileOpen(false)
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const currentPage = NAV_ITEMS.find((item) =>
    item.end ? location.pathname === item.path : location.pathname.startsWith(item.path),
  )
  // The simulator wants the full viewport; every other page reads better with
  // the usual page padding and a max width.
  const isWide = location.pathname.startsWith('/simulator')

  return (
    <div className="flex min-h-screen">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-primary-600 focus:px-4 focus:py-2 focus:text-white"
      >
        Skip to content
      </a>

      <aside className="hidden w-64 shrink-0 flex-col bg-ink-950 p-4 lg:flex">
        <SidebarContent />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="animate-fade-in absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-ink-950 p-4 shadow-pop">
            <SidebarContent onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="surface sticky top-0 z-30 flex items-center gap-3 border-b px-4 py-3 backdrop-blur lg:px-8"
          style={{ backgroundColor: 'rgb(var(--surface-card) / 0.9)' }}
        >
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            aria-expanded={mobileOpen}
            className="-ml-1 rounded-lg p-2 transition-colors hover:bg-[rgb(var(--surface-sunken))] lg:hidden"
          >
            <Menu size={20} />
          </button>

          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">{currentPage?.name ?? 'Not found'}</p>
          </div>

          <button
            type="button"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            className="rounded-lg p-2 transition-colors hover:bg-[rgb(var(--surface-sunken))]"
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </header>

        <main
          id="main-content"
          className={cx('flex-1', isWide ? 'p-3 lg:p-5' : 'px-4 py-6 lg:px-8 lg:py-8')}
        >
          <div className={cx('mx-auto w-full', isWide ? 'max-w-none' : 'max-w-7xl')}>{children}</div>
        </main>

        {!isWide && (
          <footer className="text-faint px-4 py-6 text-center text-xs lg:px-8">
            QFleet · quantum-inspired multi-objective optimisation for maritime decarbonisation
          </footer>
        )}
      </div>
    </div>
  )
}
