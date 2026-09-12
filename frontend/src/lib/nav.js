/**
 * Navigation model, shared by the top bar and the mobile drawer.
 *
 * Each item carries a `key` that matches a module key in the backend's
 * `auth/permissions.py` catalogue. That string is the contract: the admin
 * grants `benchmarks`, the server guards `/api/benchmarks` with it, and this
 * file decides whether the link renders. Renaming one means renaming all
 * three in the same commit.
 */
import {
  Activity,
  BarChart3,
  Compass,
  Fuel,
  LayoutDashboard,
  Radar,
  ShieldCheck,
  Ship,
  SlidersHorizontal,
  Users,
} from 'lucide-react'

export const NAV_ITEMS = [
  {
    key: 'dashboard',
    name: 'Dashboard',
    path: '/',
    icon: LayoutDashboard,
    end: true,
    blurb: 'Fleet at a glance',
  },
  {
    key: 'simulator',
    name: 'Fleet Digital Twin',
    path: '/simulator',
    icon: Radar,
    blurb: 'See your fleet in motion',
  },
  {
    key: 'optimize',
    name: 'Fleet Optimizer',
    path: '/optimize',
    icon: Compass,
    blurb: 'Optimize fuel, CO₂ and cost',
  },
  {
    key: 'predict',
    name: 'Fuel Prediction',
    path: '/predict',
    icon: Activity,
    blurb: 'Predict voyage fuel',
  },
  {
    key: 'compliance',
    name: 'Compliance',
    path: '/compliance',
    icon: ShieldCheck,
    blurb: 'Which vessels need attention',
  },
  {
    key: 'sandbox',
    name: 'What-if',
    path: '/sandbox',
    icon: SlidersHorizontal,
    blurb: 'Change a lever, see the impact',
    role: 'ADMIN',
  },
  {
    key: 'fleet',
    name: 'Fleet & Lanes',
    path: '/fleet',
    icon: Ship,
    blurb: 'Vessels and routes',
  },
  {
    key: 'scenarios',
    name: 'Scenarios',
    path: '/scenarios',
    icon: Fuel,
    blurb: 'Fuel transition planning',
    role: 'ADMIN',
  },
  {
    key: 'benchmarks',
    name: 'Benchmarks',
    path: '/benchmarks',
    icon: BarChart3,
    blurb: 'Which solver performs best',
    role: 'ADMIN',
  },
  {
    // No module key: employee management is not grantable. It follows the
    // role and nothing else, so an administrator cannot hand out account
    // control by ticking a box.
    name: 'Employees',
    path: '/admin',
    icon: Users,
    blurb: 'Accounts and access',
    role: 'ADMIN',
  },
]

/**
 * The items a given session may see.
 *
 * Three filters, doing different jobs. `hidden` drops an item from the
 * navigation while leaving its route and its title intact. `role` gates what
 * a rank may see at all. `key` against the session's granted modules gates
 * what this particular person was given. An item needs to pass all three.
 *
 * Accepts a session object; a bare role string still works so older callers
 * and tests keep behaving. With no permission list to check against — an
 * older token, or a role string — the role filter alone applies, which is
 * what the product did before per-employee access existed.
 */
export function navItemsFor(sessionOrRole) {
  const session = typeof sessionOrRole === 'string' ? { role: sessionOrRole } : sessionOrRole
  const role = session?.role
  const granted = Array.isArray(session?.permissions) ? session.permissions : null

  return NAV_ITEMS.filter((item) => {
    if (item.hidden) return false
    if (item.role && item.role !== role) return false
    if (item.key && granted && !granted.includes(item.key)) return false
    return true
  })
}

/** Whether this session may open a given module. */
export function canAccess(session, key) {
  if (!key) return true
  const granted = Array.isArray(session?.permissions) ? session.permissions : null
  if (!granted) return true
  return granted.includes(key)
}

export default NAV_ITEMS
