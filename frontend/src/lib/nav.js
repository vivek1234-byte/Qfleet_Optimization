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
    // Shown to administrators only. This hides a link; it does not protect
    // anything — `/api/admin/*` is behind `require_admin` on the server, and
    // that is the check that matters. See backend/auth/deps.py.
    role: 'ADMIN',
  },
]

/** The items a given role should see in the sidebar. */
export function navItemsFor(role) {
  return NAV_ITEMS.filter((item) => !item.role || item.role === role)
}

export default NAV_ITEMS
