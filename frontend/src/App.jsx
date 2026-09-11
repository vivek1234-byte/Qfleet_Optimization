import { BrowserRouter, Route, Routes } from 'react-router-dom'

import AppShell from './components/AppShell'
import Benchmarks from './pages/Benchmarks'
import Dashboard from './pages/Dashboard'
import Fleet from './pages/Fleet'
import NotFound from './pages/NotFound'
import Optimizer from './pages/Optimizer'
import Prediction from './pages/Prediction'
import Scenarios from './pages/Scenarios'
import Simulator from './pages/Simulator'

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/simulator" element={<Simulator />} />
          <Route path="/optimize" element={<Optimizer />} />
          <Route path="/predict" element={<Prediction />} />
          <Route path="/fleet" element={<Fleet />} />
          <Route path="/scenarios" element={<Scenarios />} />
          <Route path="/benchmarks" element={<Benchmarks />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  )
}
