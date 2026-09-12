import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import RequireAuth, { RequireAdmin } from './components/RequireAuth'
import Admin from './pages/Admin'
import Benchmarks from './pages/Benchmarks'
import Compliance from './pages/Compliance'
import Dashboard from './pages/Dashboard'
import Fleet from './pages/Fleet'
import Login from './pages/Login'
import NotFound from './pages/NotFound'
import Optimizer from './pages/Optimizer'
import Prediction from './pages/Prediction'
import Sandbox from './pages/Sandbox'
import Scenarios from './pages/Scenarios'
import Simulator from './pages/Simulator'
import { revalidate, useSession } from './lib/auth'

/**
 * Already signed in? The login screen has nothing to offer.
 *
 * This redirect has to resolve the *same* destination the login page does.
 * When they disagreed, signing in raced: the page navigated to the deep link
 * the user had asked for while this one sent them to the dashboard, and the
 * dashboard won.
 */
function LoginRoute() {
  const { session } = useSession()
  const location = useLocation()
  if (!session) return <Login />
  return <Navigate to={location.state?.from?.pathname ?? '/'} replace />
}

export default function App() {
  // A token restored from storage is checked against the server once, before
  // anything behind the gate renders. Without this a revoked account keeps a
  // working-looking dashboard until its token expires.
  useEffect(() => {
    revalidate()
  }, [])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginRoute />} />

        {/* Everything below the gate shares one AppShell, so the sidebar and
            header are mounted once rather than per page. */}
        <Route element={<RequireAuth />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/simulator" element={<Simulator />} />
          <Route path="/sandbox" element={<RequireAdmin><Sandbox /></RequireAdmin>} />
          <Route path="/optimize" element={<Optimizer />} />
          <Route path="/predict" element={<Prediction />} />
          <Route path="/fleet" element={<Fleet />} />
          <Route path="/compliance" element={<Compliance />} />
          <Route path="/scenarios" element={<RequireAdmin><Scenarios /></RequireAdmin>} />
          <Route path="/benchmarks" element={<RequireAdmin><Benchmarks /></RequireAdmin>} />
          {/* Administrators only. `RequireAdmin` sits inside the group so the
              shell is not remounted on the way in; the server refuses the
              calls behind this page regardless of what the client renders. */}
          <Route
            path="/admin"
            element={
              <RequireAdmin>
                <Admin />
              </RequireAdmin>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
