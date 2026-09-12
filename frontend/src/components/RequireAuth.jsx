/**
 * Route guard.
 *
 * Sends anyone without a session to the login screen, remembering where they
 * were going so sign-in returns them there rather than dumping them on the
 * dashboard.
 *
 * Two things it deliberately does *not* do:
 *
 * * It does not render children while a stored token is still being checked.
 *   Showing the dashboard first and yanking it back on a 401 is worse than a
 *   moment of nothing.
 * * It does not pretend to be authorization. `requireAdmin` below keeps the
 *   Employees page out of an ordinary employee's way, but the server refuses
 *   the calls behind it regardless — see backend/auth/deps.py.
 */
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import AppShell from './AppShell'
import { Spinner } from './ui'
import { useSession } from '../lib/auth'
import { canAccess } from '../lib/nav'

export default function RequireAuth() {
  const { session, status } = useSession()
  const location = useLocation()

  if (status === 'checking') {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner label="Checking your session" />
      </div>
    )
  }

  if (!session) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return (
    <AppShell>
      <Outlet />
    </AppShell>
  )
}

/**
 * Wraps a single route inside the authenticated group, so the shell is not
 * remounted when moving between an admin page and an ordinary one.
 */
export function RequireAdmin({ children }) {
  const { session } = useSession()
  if (session?.role !== 'ADMIN') return <Navigate to="/" replace />
  return children
}

/**
 * Gates one route on a module the administrator granted.
 *
 * Same standing as `RequireAdmin`: this stops the page rendering, the
 * `require_module` dependency in `backend/main.py` stops the data arriving.
 * Someone who types `/predict` without the grant lands on the dashboard
 * rather than on a page of failed requests.
 */
export function RequireModule({ module, children }) {
  const { session } = useSession()
  if (!canAccess(session, module)) return <Navigate to="/" replace />
  return children
}
