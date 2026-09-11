/**
 * Fleet optimiser: configure a problem, run a solver, read the plan.
 *
 * Everything on this page comes from a real solver run — there is no canned
 * result anywhere in it. The "Sail this plan" button hands the result to the
 * simulator, which is the demo's strongest single moment: the numbers on this
 * page become ships moving on the map.
 */
import {
  Coins,
  Droplets,
  Leaf,
  Play,
  Radar,
  Scale,
  Settings2,
  Sparkles,
  Timer,
  Trophy,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  Cell,
  Line,
  LineChart,
  Scatter,
  ScatterChart,
  ZAxis,
} from 'recharts'

import {
  ChartFrame,
  ThemedGrid,
  ThemedLegend,
  ThemedTooltip,
  ThemedXAxis,
  ThemedYAxis,
} from '../components/charts'
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  DataTable,
  EmptyState,
  ErrorState,
  MeterRow,
  NumberInput,
  PageHeader,
  RangeInput,
  Select,
  Skeleton,
  StatCard,
  cx,
} from '../components/ui'
import { useAsync, useFetch } from '../hooks/useApi'
import api from '../lib/api'
import { OPTIMIZER_PRESETS, algorithmColor, fuelColor } from '../lib/domain'
import { compact, num, pct, seconds, usd } from '../lib/format'
import { setActivePlan } from '../lib/planStore'

const EMPTY = []
const EMPTY_OBJECT = {}

const OBJECTIVE_META = {
  fuel_consumption_tons: { label: 'Fuel', icon: Droplets, accent: 'primary', unit: 't' },
  co2_emissions_tons: { label: 'CO₂e', icon: Leaf, accent: 'eco', unit: 't' },
  operational_cost_usd: { label: 'Operating cost', icon: Coins, accent: 'amber', unit: '' },
}

const TABS = [
  { id: 'plan', label: 'Deployment plan' },
  { id: 'pareto', label: 'Pareto front' },
  { id: 'convergence', label: 'Convergence' },
  { id: 'compare', label: 'Algorithm comparison' },
]

function formatObjectiveValue(key, value) {
  return key === 'operational_cost_usd' ? usd(value, { compact: true }) : `${compact(value)} t`
}

/* -------------------------------------------------------------------------- */
/* Configuration form                                                          */
/* -------------------------------------------------------------------------- */
function ConfigPanel({ config, setConfig, algorithms, fuels, onRun, running, presetId, setPresetId }) {
  const set = (key) => (event) => {
    const raw = event.target.value
    setConfig((c) => ({ ...c, [key]: raw === '' ? '' : Number(raw) }))
    setPresetId(null)
  }

  const toggleFuel = (name) => {
    setConfig((c) => {
      const current = new Set(c.fuel_types)
      if (current.has(name)) current.delete(name)
      else current.add(name)
      // An empty list means "all fuels" to the backend, but leaving one fuel
      // selected then unselecting it should not silently widen the search.
      return { ...c, fuel_types: [...current] }
    })
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="field-label">Preset</p>
        <div className="grid grid-cols-3 gap-1.5">
          {OPTIMIZER_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              title={preset.hint}
              onClick={() => {
                setConfig((c) => ({ ...c, ...preset.config }))
                setPresetId(preset.id)
              }}
              className={cx(
                'rounded-lg border px-2 py-1.5 text-xs font-medium transition-colors',
                presetId === preset.id
                  ? 'border-primary-500 bg-primary-50 text-primary-700 dark:bg-primary-950/50 dark:text-primary-200'
                  : 'hover:bg-[rgb(var(--surface-sunken))]',
              )}
              style={
                presetId === preset.id ? undefined : { borderColor: 'rgb(var(--border-strong))' }
              }
            >
              {preset.name}
            </button>
          ))}
        </div>
        <p className="text-faint mt-1 text-xs">
          {OPTIMIZER_PRESETS.find((p) => p.id === presetId)?.hint ?? 'Custom configuration.'}
        </p>
      </div>

      <Select
        label="Algorithm"
        value={config.algorithm}
        onChange={(e) => setConfig((c) => ({ ...c, algorithm: e.target.value }))}
        options={(algorithms ?? []).map((a) => ({
          value: a.id,
          label: `${a.name}${a.quantum_inspired ? ' · quantum-inspired' : ''}`,
        }))}
        hint={(algorithms ?? []).find((a) => a.id === config.algorithm)?.description}
      />

      <div className="grid grid-cols-2 gap-3">
        <NumberInput
          label="Vessels"
          min={2}
          max={60}
          value={config.n_vessels}
          onChange={set('n_vessels')}
        />
        <NumberInput
          label="Routes"
          min={1}
          max={16}
          value={config.n_routes}
          onChange={set('n_routes')}
        />
        <NumberInput
          label="Iterations"
          min={10}
          max={1000}
          step={10}
          value={config.max_iterations}
          onChange={set('max_iterations')}
        />
        <NumberInput
          label="Population"
          min={10}
          max={300}
          step={10}
          value={config.population_size}
          onChange={set('population_size')}
        />
      </div>

      <NumberInput
        label="Carbon price"
        unit="$/t"
        min={0}
        max={500}
        step={5}
        value={config.carbon_price_usd_per_ton}
        onChange={set('carbon_price_usd_per_ton')}
        hint="Priced into the cost objective. EU ETS is the obvious sensitivity to show."
      />

      <div>
        <p className="field-label">Objective weights</p>
        <div className="space-y-2.5">
          {['fuel', 'co2', 'cost'].map((key, index) => (
            <RangeInput
              key={key}
              label={['Fuel', 'CO₂e', 'Cost'][index]}
              unit=""
              min={0}
              max={1}
              step={0.05}
              value={config.weights[index]}
              onChange={(e) =>
                setConfig((c) => {
                  const weights = [...c.weights]
                  weights[index] = Number(e.target.value)
                  return { ...c, weights }
                })
              }
            />
          ))}
        </div>
        <p className="text-faint mt-1 text-xs">
          Used to pick one solution off the Pareto front, and to scalarise for the
          single-objective solvers. Normalised before use.
        </p>
      </div>

      <div>
        <p className="field-label">Fuels the solver may choose</p>
        <div className="grid grid-cols-2 gap-1.5">
          {(fuels ?? []).map((fuel) => (
            <Checkbox
              key={fuel.name}
              label={fuel.name}
              checked={config.fuel_types.includes(fuel.name)}
              onChange={() => toggleFuel(fuel.name)}
            />
          ))}
        </div>
        <p className="text-faint mt-1 text-xs">
          {config.fuel_types.length === 0
            ? 'Nothing selected — the backend will offer the full fuel set.'
            : `${config.fuel_types.length} selected.`}
        </p>
      </div>

      <NumberInput
        label="Random seed"
        min={0}
        max={99999}
        value={config.seed}
        onChange={set('seed')}
        hint="Fixed so a run on stage reproduces the one you rehearsed."
      />

      <Button
        className="w-full"
        size="lg"
        icon={Play}
        loading={running}
        onClick={onRun}
      >
        Run optimisation
      </Button>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Result views                                                                */
/* -------------------------------------------------------------------------- */
function PlanView({ result }) {
  const plan = result.plan
  if (!plan) {
    return (
      <Alert tone="info" title="No plan in this response">
        Re-run with &quot;Include deployment plan&quot; to see per-vessel assignments.
      </Alert>
    )
  }

  const breakdown = Object.entries(plan.cost_breakdown ?? {})
  const breakdownTotal = breakdown.reduce((a, [, v]) => a + v, 0)
  const fuelMix = Object.entries(plan.fuel_mix ?? {}).sort((a, b) => b[1] - a[1])
  const coverage = Object.entries(plan.route_coverage ?? {})

  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Cost breakdown" className="lg:col-span-1">
          <div className="space-y-2.5">
            {breakdown.map(([key, value]) => (
              <MeterRow
                key={key}
                label={key.replace(/_usd$/, '').replace(/_/g, ' ')}
                value={value}
                max={breakdownTotal}
                display={usd(value, { compact: true })}
              />
            ))}
          </div>
          <p className="text-faint mt-3 text-xs">
            Vessel opex is charged per day at sea, so a slower plan trades bunker cost for
            time-charter cost. That tension is why the cost saving is always smaller than the
            fuel saving.
          </p>
        </Card>

        <Card title="Fuel mix" className="lg:col-span-1">
          <div className="space-y-2.5">
            {fuelMix.map(([name, count]) => (
              <div key={name} className="flex items-center gap-3">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: fuelColor(name) }}
                  aria-hidden
                />
                <span className="flex-1 text-sm">{name}</span>
                <span className="numeric text-faint text-sm">{count} vessels</span>
              </div>
            ))}
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-y-1.5 border-t pt-3 text-sm"
            style={{ borderColor: 'rgb(var(--border-subtle))' }}
          >
            <dt className="text-faint">Mean speed</dt>
            <dd className="numeric text-right">{num(plan.average_speed_knots, 2)} kn</dd>
            <dt className="text-faint">Mean shore power</dt>
            <dd className="numeric text-right">{pct(plan.average_shore_power_pct)}</dd>
          </dl>
        </Card>

        <Card title="Route coverage" className="lg:col-span-1">
          <div className="space-y-2.5">
            {coverage.map(([name, info]) => (
              <div key={name}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-sm">{name}</span>
                  <Badge tone={info.covered ? 'eco' : 'danger'}>
                    {info.covered ? 'covered' : 'short'}
                  </Badge>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[rgb(var(--surface-sunken))]">
                    <div
                      className={cx('h-full rounded-full', info.covered ? 'bg-eco-500' : 'bg-rose-500')}
                      style={{
                        width: `${Math.min((info.capacity_tons / Math.max(info.demand_tons, 1)) * 100, 100)}%`,
                      }}
                    />
                  </div>
                  <span className="numeric text-faint w-28 shrink-0 text-right text-xs">
                    {compact(info.capacity_tons)} / {compact(info.demand_tons)} t
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card
        title="Vessel assignments"
        description={`${plan.assignments.length} vessels · every row is a decision the solver made`}
      >
        <DataTable
          columns={[
            { key: 'vessel_name', header: 'Vessel' },
            { key: 'vessel_type', header: 'Class' },
            { key: 'route_name', header: 'Lane' },
            {
              key: 'fuel_type',
              header: 'Fuel',
              render: (row) => (
                <span className="inline-flex items-center gap-1.5">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: fuelColor(row.fuel_type) }}
                    aria-hidden
                  />
                  {row.fuel_type}
                </span>
              ),
            },
            {
              key: 'speed_knots',
              header: 'Speed',
              align: 'right',
              render: (row) => `${num(row.speed_knots, 2)} kn`,
            },
            {
              key: 'shore_power_pct',
              header: 'Shore pwr',
              align: 'right',
              render: (row) => pct(row.shore_power_pct, 0),
            },
            {
              key: 'voyage_days',
              header: 'Voyage',
              align: 'right',
              render: (row) => `${num(row.voyage_days, 1)} d`,
            },
            {
              key: 'fuel_tons',
              header: 'Fuel',
              align: 'right',
              render: (row) => `${num(row.fuel_tons)} t`,
            },
            {
              key: 'co2_tons',
              header: 'CO₂e',
              align: 'right',
              render: (row) => `${num(row.co2_tons)} t`,
            },
            {
              key: 'cost_usd',
              header: 'Cost',
              align: 'right',
              render: (row) => usd(row.cost_usd, { compact: true }),
            },
          ]}
          rows={plan.assignments}
          getRowKey={(row) => `${row.vessel_id}-${row.route_id}`}
        />
      </Card>
    </div>
  )
}

function ParetoView({ result }) {
  const front = result.pareto_front ?? EMPTY
  const best = result.best_objectives

  const points = useMemo(() => {
    const rows = front.map((p, i) => ({
      index: i,
      fuel: p.fuel_consumption_tons,
      co2: p.co2_emissions_tons,
      cost: p.operational_cost_usd,
      feasible: p.feasible,
      isBest: false,
    }))
    if (!best || !rows.length) return rows
    // Nearest front member to the recommended solution, measured on each
    // objective's own scale so cost in dollars does not swamp tonnes.
    const span = (key) => {
      const values = rows.map((r) => r[key])
      return Math.max(...values) - Math.min(...values) || 1
    }
    const spans = { fuel: span('fuel'), co2: span('co2'), cost: span('cost') }
    const target = {
      fuel: best.fuel_consumption_tons,
      co2: best.co2_emissions_tons,
      cost: best.operational_cost_usd,
    }
    let bestIndex = 0
    let bestDistance = Infinity
    rows.forEach((row, i) => {
      const d = ['fuel', 'co2', 'cost'].reduce(
        (a, key) => a + ((row[key] - target[key]) / spans[key]) ** 2,
        0,
      )
      if (d < bestDistance) {
        bestDistance = d
        bestIndex = i
      }
    })
    rows[bestIndex].isBest = true
    return rows
  }, [front, best])

  if (!points.length) {
    return (
      <EmptyState
        icon={Scale}
        title="This solver returned a single solution"
        description="QGA and PSO optimise a scalarised objective, so there is no front to plot. Run QPSO or NSGA-II for a Pareto front."
      />
    )
  }

  return (
    <div className="space-y-5">
      <Card
        title="Trade-off surface"
        description="Every point is a non-dominated deployment plan. Bubble size is operating cost."
      >
        <ChartFrame height={340}>
          <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
            <ThemedGrid vertical />
            <ThemedXAxis
              type="number"
              dataKey="fuel"
              name="Fuel"
              unit=" t"
              domain={['dataMin - 20', 'dataMax + 20']}
              tickFormatter={(v) => num(v, 0)}
              label={{
                value: 'Fuel consumption (t)',
                position: 'insideBottom',
                offset: -18,
                fontSize: 12,
              }}
            />
            <ThemedYAxis
              type="number"
              dataKey="co2"
              name="CO₂e"
              unit=" t"
              domain={['dataMin - 40', 'dataMax + 40']}
              tickFormatter={(v) => num(v, 0)}
              width={72}
              label={{
                value: 'CO₂e (t)',
                angle: -90,
                position: 'insideLeft',
                offset: 6,
                fontSize: 12,
              }}
            />
            <ZAxis type="number" dataKey="cost" range={[80, 420]} name="Cost" unit=" USD" />
            <ThemedTooltip
              formatter={(value, name) =>
                name === 'Cost' ? usd(value) : `${num(value, 1)} t`
              }
            />
            <Scatter data={points} fill="#06a3ee">
              {points.map((p) => (
                <Cell key={p.index} fill={p.isBest ? '#f59e0b' : p.feasible ? '#06a3ee' : '#f43f5e'} />
              ))}
            </Scatter>
          </ScatterChart>
        </ChartFrame>
        <p className="text-faint mt-3 text-xs">
          Fuel, CO₂ and cost are strongly correlated, so an honest front here is narrow — a handful
          of points, not a smooth curve. Amber marks the front member closest to the solution the
          solver recommends under your objective weights.
        </p>
      </Card>

      <Card title="Front members" description={`${front.length} non-dominated solutions`}>
        <DataTable
          columns={[
            { key: 'index', header: '#', render: (row) => row.index + 1 },
            { key: 'fuel', header: 'Fuel (t)', align: 'right', render: (r) => num(r.fuel, 1) },
            { key: 'co2', header: 'CO₂e (t)', align: 'right', render: (r) => num(r.co2, 1) },
            { key: 'cost', header: 'Cost', align: 'right', render: (r) => usd(r.cost) },
            {
              key: 'feasible',
              header: 'Feasible',
              render: (r) => (
                <Badge tone={r.feasible ? 'eco' : 'danger'}>{r.feasible ? 'yes' : 'no'}</Badge>
              ),
            },
          ]}
          rows={points}
          getRowKey={(row) => row.index}
          highlightRow={(row) => row.isBest}
        />
      </Card>
    </div>
  )
}

function ConvergenceView({ result }) {
  const data = (result.convergence_history ?? []).map((value, index) => ({
    iteration: index + 1,
    value,
  }))
  if (!data.length) return <EmptyState icon={Timer} title="No convergence history recorded" />
  return (
    <Card
      title="Convergence"
      description="Normalised weighted objective at each iteration — lower is better. Every algorithm reports on this same scale, so the curves are comparable."
    >
      <ChartFrame height={320}>
        <LineChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 0 }}>
          <ThemedGrid />
          <ThemedXAxis
            dataKey="iteration"
            label={{ value: 'Iteration', position: 'insideBottom', offset: -26, fontSize: 12 }}
          />
          <ThemedYAxis domain={['auto', 'auto']} tickFormatter={(v) => v.toFixed(3)} />
          <ThemedTooltip formatter={(v) => v.toFixed(6)} />
          <Line
            type="monotone"
            dataKey="value"
            stroke={algorithmColor(result.algorithm)}
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ChartFrame>
    </Card>
  )
}

function CompareView({ compare, onRun, running }) {
  const data = compare?.comparison ?? EMPTY
  const convergence = compare?.convergence ?? EMPTY_OBJECT

  const series = useMemo(() => {
    const ids = Object.keys(convergence)
    if (!ids.length) return []
    const length = Math.max(...ids.map((id) => convergence[id].length))
    return Array.from({ length }, (_, i) => {
      const row = { iteration: i + 1 }
      ids.forEach((id) => {
        row[id] = convergence[id][i]
      })
      return row
    })
  }, [convergence])

  if (!data.length) {
    return (
      <EmptyState
        icon={Trophy}
        title="Run all four solvers on the same problem"
        description="Same fleet, same seed, same iteration budget. This is the comparison a reviewer will ask for, so it is worth having on screen before they do."
        action={
          <Button icon={Play} loading={running} onClick={onRun}>
            Run comparison
          </Button>
        }
      />
    )
  }

  const savingsData = data.map((row) => ({
    algorithm: row.algorithm,
    name: row.algorithm.toUpperCase(),
    fuel: row.savings_pct?.fuel_consumption_tons ?? 0,
    co2: row.savings_pct?.co2_emissions_tons ?? 0,
    cost: row.savings_pct?.operational_cost_usd ?? 0,
  }))

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Alert tone={compare.winner ? 'info' : 'warning'} className="flex-1">
          Best scalarised objective on this problem: <strong>{compare.winner?.toUpperCase()}</strong>
          . A single run is one sample — use the Benchmarks page for a multi-seed result with
          standard deviations before claiming a winner.
        </Alert>
        <Button variant="secondary" icon={Play} loading={running} onClick={onRun}>
          Re-run
        </Button>
      </div>

      <Card title="Savings against the greedy baseline" description="Per objective, same problem instance">
        <ChartFrame height={300}>
          <BarChart data={savingsData} margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
            <ThemedGrid />
            <ThemedXAxis dataKey="name" />
            <ThemedYAxis unit="%" />
            <ThemedTooltip formatter={(v) => pct(v)} />
            <ThemedLegend />
            <Bar dataKey="fuel" name="Fuel" fill="#06a3ee" radius={[4, 4, 0, 0]} />
            <Bar dataKey="co2" name="CO₂e" fill="#15af73" radius={[4, 4, 0, 0]} />
            <Bar dataKey="cost" name="Cost" fill="#f59e0b" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ChartFrame>
      </Card>

      {series.length > 0 && (
        <Card title="Convergence, all solvers" description="Normalised weighted objective, lower is better">
          <ChartFrame height={320}>
            <LineChart data={series} margin={{ top: 10, right: 20, bottom: 46, left: 0 }}>
              <ThemedGrid />
              <ThemedXAxis
                dataKey="iteration"
                label={{ value: 'Iteration', position: 'insideBottom', offset: -26, fontSize: 12 }}
              />
              <ThemedYAxis tickFormatter={(v) => v.toFixed(3)} />
              <ThemedTooltip formatter={(v) => (typeof v === 'number' ? v.toFixed(6) : v)} />
              <ThemedLegend />
              {Object.keys(convergence).map((id) => (
                <Line
                  key={id}
                  type="monotone"
                  dataKey={id}
                  name={id.toUpperCase()}
                  stroke={algorithmColor(id)}
                  strokeWidth={2}
                  dot={false}
                />
              ))}
            </LineChart>
          </ChartFrame>
        </Card>
      )}

      <Card title="Run detail">
        <DataTable
          columns={[
            {
              key: 'algorithm_name',
              header: 'Algorithm',
              render: (row) => (
                <span className="inline-flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: algorithmColor(row.algorithm) }}
                    aria-hidden
                  />
                  {row.algorithm_name}
                </span>
              ),
            },
            {
              key: 'quantum_inspired',
              header: 'Family',
              render: (row) => (
                <Badge tone={row.quantum_inspired ? 'primary' : 'neutral'}>
                  {row.quantum_inspired ? 'quantum-inspired' : 'classical'}
                </Badge>
              ),
            },
            { key: 'rank', header: 'Rank', align: 'right' },
            {
              key: 'final_convergence',
              header: 'Objective',
              align: 'right',
              render: (row) => row.final_convergence?.toFixed(6) ?? '—',
            },
            { key: 'pareto_size', header: 'Front', align: 'right' },
            {
              key: 'time_seconds',
              header: 'Time',
              align: 'right',
              render: (row) => seconds(row.time_seconds),
            },
            { key: 'n_evaluations', header: 'Evals', align: 'right', render: (r) => num(r.n_evaluations) },
            {
              key: 'feasible',
              header: 'Feasible',
              render: (row) => (
                <Badge tone={row.feasible ? 'eco' : 'danger'}>{row.feasible ? 'yes' : 'no'}</Badge>
              ),
            },
          ]}
          rows={data}
          getRowKey={(row) => row.algorithm}
          highlightRow={(row) => row.algorithm === compare.winner}
        />
      </Card>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */
export default function Optimizer() {
  const navigate = useNavigate()
  const algorithms = useFetch((signal) => api.optimization.algorithms({ signal }), [])
  const fuels = useFetch((signal) => api.scenarios.fuels({ signal }), [])

  const optimise = useAsync((signal, body) => api.optimization.optimize(body, { signal }))
  const compare = useAsync((signal, body) => api.optimization.compare(body, { signal }))

  const [presetId, setPresetId] = useState('demo')
  const [tab, setTab] = useState('plan')
  const [config, setConfig] = useState({
    ...OPTIMIZER_PRESETS[0].config,
    algorithm: 'qpso',
    seed: 42,
    carbon_price_usd_per_ton: 0,
    weights: [0.4, 0.4, 0.2],
    fuel_types: [],
  })

  const requestBody = () => ({
    n_vessels: Number(config.n_vessels) || 8,
    n_routes: Number(config.n_routes) || 5,
    max_iterations: Number(config.max_iterations) || 80,
    population_size: Number(config.population_size) || 40,
    carbon_price_usd_per_ton: Number(config.carbon_price_usd_per_ton) || 0,
    seed: Number(config.seed),
    objective_weights: config.weights,
    fuel_types: config.fuel_types.length ? config.fuel_types : null,
  })

  const runOptimise = async () => {
    const result = await optimise.run({
      ...requestBody(),
      algorithm: config.algorithm,
      include_plan: true,
    })
    if (result) setTab('plan')
  }

  // /compare takes the problem definition but not objective_weights — it
  // scores every solver on the same fixed scalarisation so the comparison is
  // like for like.
  const runCompare = () => {
    const { objective_weights: _weights, ...problem } = requestBody()
    return compare.run({ ...problem, algorithms: ['qpso', 'qga', 'pso', 'nsga2'] })
  }

  const result = optimise.data

  const sailPlan = () => {
    if (!result) return
    setActivePlan(result, 'optimizer')
    navigate('/simulator')
  }

  return (
    <>
      <PageHeader
        title="Fleet optimiser"
        description="Choose which vessel sails which lane, how fast, on what fuel, and how much shore power to draw — minimising fuel, CO₂ and cost together."
        actions={
          result && (
            <Button variant="eco" icon={Radar} onClick={sailPlan}>
              Sail this plan
            </Button>
          )
        }
      />

      <div className="grid gap-5 xl:grid-cols-[20rem_minmax(0,1fr)]">
        <div className="xl:sticky xl:top-20 xl:self-start">
          <Card title="Problem" description="What to solve" className="overflow-visible">
            {algorithms.error ? (
              <ErrorState error={algorithms.error} onRetry={algorithms.refetch} />
            ) : algorithms.loading ? (
              <div className="space-y-3">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : (
              <ConfigPanel
                config={config}
                setConfig={setConfig}
                algorithms={algorithms.data}
                fuels={fuels.data}
                onRun={runOptimise}
                running={optimise.loading}
                presetId={presetId}
                setPresetId={setPresetId}
              />
            )}
          </Card>
        </div>

        <div className="min-w-0 space-y-5">
          {optimise.error && <ErrorState error={optimise.error} onRetry={runOptimise} />}

          {!result && !optimise.loading && (
            <Card>
              <EmptyState
                icon={Settings2}
                title="Nothing solved yet"
                description="Pick a preset and run. The demo preset finishes in well under a second, which is the one to use with an audience watching."
                action={
                  <Button icon={Play} onClick={runOptimise} loading={optimise.loading}>
                    Run optimisation
                  </Button>
                }
              />
            </Card>
          )}

          {optimise.loading && (
            <div className="grid gap-4 sm:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-28 w-full rounded-xl" />
              ))}
            </div>
          )}

          {result && (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                {(result.objective_names ?? []).map((key) => {
                  const meta = OBJECTIVE_META[key] ?? { label: key, icon: Sparkles, accent: 'slate' }
                  const improvement = result.improvement_vs_baseline?.[key]
                  return (
                    <StatCard
                      key={key}
                      label={meta.label}
                      value={formatObjectiveValue(key, result.best_objectives?.[key])}
                      icon={meta.icon}
                      accent={meta.accent}
                      delta={improvement?.percent_saving}
                      deltaLabel="vs baseline"
                      hint={
                        improvement
                          ? `Baseline ${formatObjectiveValue(key, improvement.baseline)}`
                          : undefined
                      }
                    />
                  )
                })}
              </div>

              <div className="card flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3 text-sm">
                <span className="inline-flex items-center gap-2 font-medium">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: algorithmColor(result.algorithm) }}
                    aria-hidden
                  />
                  {result.algorithm_name}
                </span>
                <Badge tone={result.quantum_inspired ? 'primary' : 'neutral'}>
                  {result.quantum_inspired ? 'quantum-inspired' : 'classical'}
                </Badge>
                <Badge tone={result.feasible ? 'eco' : 'danger'}>
                  {result.feasible ? 'all constraints satisfied' : 'constraint violation'}
                </Badge>
                <span className="text-faint">
                  {seconds(result.elapsed_seconds)} · {num(result.n_evaluations)} evaluations ·{' '}
                  {result.iterations} iterations
                </span>
                {result.multi_objective && (
                  <span className="text-faint">
                    front {result.pareto_size} ({result.feasible_solutions} feasible)
                  </span>
                )}
              </div>

              <div
                className="flex gap-1 overflow-x-auto border-b"
                style={{ borderColor: 'rgb(var(--border-subtle))' }}
                role="tablist"
              >
                {TABS.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    role="tab"
                    aria-selected={tab === t.id}
                    onClick={() => {
                      setTab(t.id)
                      if (t.id === 'compare' && !compare.data && !compare.loading) runCompare()
                    }}
                    className={cx(
                      '-mb-px whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium transition-colors',
                      tab === t.id
                        ? 'border-primary-600 text-primary-700 dark:text-primary-300'
                        : 'text-faint border-transparent hover:text-[rgb(var(--text-primary))]',
                    )}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {tab === 'plan' && <PlanView result={result} />}
              {tab === 'pareto' && <ParetoView result={result} />}
              {tab === 'convergence' && <ConvergenceView result={result} />}
              {tab === 'compare' && (
                <>
                  {compare.error && <ErrorState error={compare.error} onRetry={runCompare} />}
                  {compare.loading && <Skeleton className="h-72 w-full rounded-xl" />}
                  {!compare.loading && (
                    <CompareView compare={compare.data} onRun={runCompare} running={compare.loading} />
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </>
  )
}
