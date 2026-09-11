/** Navigation model, shared by the sidebar and the header title. */
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
  { name: 'Dashboard', path: '/', icon: LayoutDashboard, end: true, blurb: 'Fleet at a glance' },
  { name: 'Live Simulator', path: '/simulator', icon: Radar, blurb: 'Voyages in motion' },
  { name: 'What-if Sandbox', path: '/sandbox', icon: SlidersHorizontal, blurb: 'Move a lever, re-solve' },
  { name: 'Fleet Optimizer', path: '/optimize', icon: Compass, blurb: 'Plan the deployment' },
  { name: 'Compliance', path: '/compliance', icon: ShieldCheck, blurb: 'CII ratings and ECAs' },
  { name: 'Fuel Prediction', path: '/predict', icon: Activity, blurb: 'What will a voyage burn' },
  { name: 'Fleet & Lanes', path: '/fleet', icon: Ship, blurb: 'Vessels and trade lanes' },
  { name: 'Scenarios', path: '/scenarios', icon: Fuel, blurb: 'Fuel transition planning' },
  { name: 'Benchmarks', path: '/benchmarks', icon: BarChart3, blurb: 'Algorithm evidence' },
  {
    name: 'Employees',
    path: '/admin',
    icon: Users,
    blurb: 'Accounts and access',
    // Administrators only. This is presentation — `/api/admin/*` is behind
    // `require_admin` on the server, and that is the check that matters. See
    // backend/auth/deps.py.
    role: 'ADMIN',
    // Kept out of the sidebar entirely, for everyone. The page is still there
    // and still works: an administrator reaches it by typing /admin, and
    // `RequireAdmin` turns anyone else away. The entry stays in this list
    // rather than being deleted because the header title is looked up here —
    // remove it and the page renders as "Not found" above a working table.
    hidden: true,
  },
]

/**
 * The items to render in the sidebar for a given role.
 *
 * Two filters, doing different jobs: `hidden` drops an item from the
 * navigation while leaving its route and its title intact, and `role` gates
 * what a given person may see. An item needs to pass both.
 */
export function navItemsFor(role) {
  return NAV_ITEMS.filter((item) => !item.hidden && (!item.role || item.role === role))
}

export default NAV_ITEMS
