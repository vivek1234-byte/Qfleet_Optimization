/** Navigation model, shared by the sidebar and the header title. */
import {
  Activity,
  BarChart3,
  Compass,
  Fuel,
  LayoutDashboard,
  Radar,
  Ship,
} from 'lucide-react'

export const NAV_ITEMS = [
  { name: 'Dashboard', path: '/', icon: LayoutDashboard, end: true, blurb: 'Fleet at a glance' },
  { name: 'Live Simulator', path: '/simulator', icon: Radar, blurb: 'Voyages in motion' },
  { name: 'Fleet Optimizer', path: '/optimize', icon: Compass, blurb: 'Plan the deployment' },
  { name: 'Fuel Prediction', path: '/predict', icon: Activity, blurb: 'What will a voyage burn' },
  { name: 'Fleet & Lanes', path: '/fleet', icon: Ship, blurb: 'Vessels and trade lanes' },
  { name: 'Scenarios', path: '/scenarios', icon: Fuel, blurb: 'Fuel transition planning' },
  { name: 'Benchmarks', path: '/benchmarks', icon: BarChart3, blurb: 'Algorithm evidence' },
]

export default NAV_ITEMS
