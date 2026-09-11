/**
 * Dashboard.
 *
 * Ten seconds to explain what this is, then one button that proves it. The
 * hero runs a real optimisation on the demo preset — nothing here is a mock —
 * and hands the result to the simulator.
 */
import {
  Activity,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Coins,
  Compass,
  Cpu,
  Droplets,
  Leaf,
  Radar,
  Ship,
  Sparkles,
  Target,
  XCircle,
} from 'lucide-react'
import { useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Cell, Pie, PieChart } from 'recharts'

import WorldMap, { useMapViewport } from '../components/WorldMap'
import { ChartFrame, ThemedTooltip } from '../components/charts'
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorState,
  MeterRow,
  PageHeader,
  Skeleton,
  StatCard,
  cx,
} from '../components/ui'
import { MAP_VIEWS, PORTS, buildLaneGeometry } from '../data/geography'
import { useAsync, useFetch } from '../hooks/useApi'
import api from '../lib/api'
import { OPTIMIZER_PRESETS, VESSEL_TYPE_COLORS } from '../lib/domain'
import { compact, num, pct, seconds, usd } from '../lib/format'
import { setActivePlan, useActivePlan } from '../lib/planStore'

const EMPTY = []

function CheckRow({ ok, label, detail }) {
  return (
    <div className="flex items-start gap-2.5 text-sm">
      {ok ? (
        <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-eco-500" aria-hidden />
      ) : (
        <XCircle size={16} className="mt-0.5 shrink-0 text-rose-500" aria-hidden />
      )}
      <div className="min-w-0">
        <p className="font-medium capitalize">{label.replace(/_/g, ' ')}</p>
        {detail && <p className="text-faint truncate text-xs">{detail}</p>}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const health = useFetch((signal) => api.health({ signal }), [])
  const registry = useFetch((signal) => api.optimization.registry({ signal }), [])
  const modelInfo = useFetch((signal) => api.prediction.modelInfo({ signal }), [])
  const algorithms = useFetch((signal) => api.optimization.algorithms({ signal }), [])
  const optimise = useAsync((signal, body) => api.optimization.optimize(body, { signal }))
  const active = useActivePlan()

  const viewport = useMapViewport(MAP_VIEWS.indianOcean.box)

  const lanes = registry.data?.lanes ?? EMPTY
  const vessels = registry.data?.vessels ?? EMPTY
  const geometries = useMemo(() => {
    const out = {}
    lanes.forEach((lane) => {
      const geometry = buildLaneGeometry(lane)
      if (geometry) out[lane.name] = geometry
    })
    return out
  }, [lanes])
  const ports = useMemo(() => Object.entries(PORTS).map(([name, p]) => ({ name, ...p })), [])

  const typeSplit = useMemo(() => {
    const counts = {}
    vessels.forEach((v) => {
      counts[v.vessel_type] = (counts[v.vessel_type] ?? 0) + 1
    })
    return Object.entries(counts).map(([name, value]) => ({ name, value }))
  }, [vessels])

  const result = optimise.data ?? active.result
  const metrics = modelInfo.data?.metrics

  const runDemo = async () => {
    const res = await optimise.run({
      ...OPTIMIZER_PRESETS[0].config,
      algorithm: 'qpso',
      seed: 42,
      include_plan: true,
    })
    if (res) setActivePlan(res, 'dashboard')
  }

  const savings = result?.improvement_vs_baseline

  return (
    <>
      <PageHeader
        title="QFleet"
        description="Quantum-inspired multi-objective optimisation for maritime decarbonisation. Decide which vessel sails which lane, at what speed, on which fuel — cutting bunker, CO₂ and cost together rather than trading one for another."
        actions={
          <>
            <Button variant="secondary" icon={Compass} onClick={() => navigate('/optimize')}>
              Open optimiser
            </Button>
            <Button icon={Sparkles} loading={optimise.loading} onClick={runDemo}>
              Run a live optimisation
            </Button>
          </>
        }
      />

      {health.error && <ErrorState error={health.error} onRetry={health.refetch} className="mb-5" />}
      {optimise.error && <ErrorState error={optimise.error} onRetry={runDemo} className="mb-5" />}

      {/* Headline result */}
      {result ? (
        <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Fuel saved"
            value={savings ? pct(savings.fuel_consumption_tons.percent_saving) : '—'}
            icon={Droplets}
            accent="primary"
            hint={
              savings
                ? `${compact(savings.fuel_consumption_tons.absolute_saving)} t off ${compact(savings.fuel_consumption_tons.baseline)} t`
                : undefined
            }
          />
          <StatCard
            label="CO₂e avoided"
            value={savings ? pct(savings.co2_emissions_tons.percent_saving) : '—'}
            icon={Leaf}
            accent="eco"
            hint={
              savings
                ? `${compact(savings.co2_emissions_tons.absolute_saving)} t per voyage cycle`
                : undefined
            }
          />
          <StatCard
            label="Cost saved"
            value={savings ? pct(savings.operational_cost_usd.percent_saving) : '—'}
            icon={Coins}
            accent="amber"
            hint={
              savings
                ? usd(savings.operational_cost_usd.absolute_saving, { compact: true })
                : undefined
            }
          />
          <StatCard
            label="Solve time"
            value={seconds(result.elapsed_seconds)}
            icon={Cpu}
            accent="violet"
            hint={`${num(result.n_evaluations)} evaluations · ${result.algorithm.toUpperCase()}`}
          />
        </div>
      ) : (
        <Card className="mb-5">
          <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-medium">Nothing optimised yet in this session.</p>
              <p className="text-faint mt-1 text-sm">
                The demo preset solves an eight-vessel, five-lane problem in well under a second
                and the result drives the live map.
              </p>
            </div>
            <Button icon={Sparkles} loading={optimise.loading} onClick={runDemo}>
              Run a live optimisation
            </Button>
          </div>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Map preview */}
        <Card
          className="flex flex-col lg:col-span-2"
          bodyClassName="flex-1 p-0"
          title="Network"
          description={`${registry.data?.lane_count ?? '—'} trade lanes serving ${registry.data?.vessel_count ?? '—'} vessels`}
          actions={
            <Button size="sm" variant="secondary" icon={Radar} onClick={() => navigate('/simulator')}>
              Open live simulator
            </Button>
          }
        >
          <div className="h-full min-h-[20rem] overflow-hidden rounded-b-xl">
            {registry.loading ? (
              <Skeleton className="h-full w-full" />
            ) : (
              <WorldMap
                viewport={viewport}
                lanes={lanes}
                geometries={geometries}
                ports={ports}
                showChokepoints={false}
                paused
              />
            )}
          </div>
        </Card>

        {/* System status */}
        <Card title="System" description="Everything this demo depends on">
          {health.loading ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <Badge tone={health.data?.status === 'healthy' ? 'eco' : 'warning'}>
                  {health.data?.status ?? 'unknown'}
                </Badge>
                <span className="text-faint text-xs">API v{health.data?.version}</span>
              </div>
              {Object.entries(health.data?.checks ?? {}).map(([name, check]) => (
                <CheckRow key={name} ok={check.ok} label={name} detail={check.detail} />
              ))}
            </div>
          )}

          <div
            className="mt-4 space-y-3 border-t pt-4"
            style={{ borderColor: 'rgb(var(--border-subtle))' }}
          >
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="text-faint">Prediction model</span>
              <span className="numeric font-medium">
                {metrics ? `R² ${num(metrics.r2, 4)}` : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="text-faint">Mean error</span>
              <span className="numeric font-medium">{metrics ? pct(metrics.mape, 2) : '—'}</span>
            </div>
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="text-faint">Trained on</span>
              <span className="numeric font-medium">
                {metrics ? `${num(metrics.n_train)} voyages` : '—'}
              </span>
            </div>
          </div>

          {typeSplit.length > 0 && (
            <div className="mt-4 border-t pt-3" style={{ borderColor: 'rgb(var(--border-subtle))' }}>
              <ChartFrame height={150}>
                <PieChart>
                  <Pie
                    data={typeSplit}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={34}
                    outerRadius={58}
                    paddingAngle={2}
                    stroke="none"
                  >
                    {typeSplit.map((entry) => (
                      <Cell
                        key={entry.name}
                        fill={VESSEL_TYPE_COLORS[entry.name] ?? '#64748b'}
                      />
                    ))}
                  </Pie>
                  <ThemedTooltip formatter={(v, n) => [`${v} vessels`, n]} />
                </PieChart>
              </ChartFrame>
              <div className="flex flex-wrap justify-center gap-x-3 gap-y-1">
                {typeSplit.map((entry) => (
                  <span key={entry.name} className="text-faint flex items-center gap-1.5 text-xs">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ backgroundColor: VESSEL_TYPE_COLORS[entry.name] ?? '#64748b' }}
                      aria-hidden
                    />
                    {entry.name} · {entry.value}
                  </span>
                ))}
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* Plan detail when we have one */}
      {result?.plan && (
        <Card
          className="mt-5"
          title="Latest plan"
          description={`${result.plan.assignments.length} vessels deployed by ${result.algorithm_name}`}
          actions={
            <Button size="sm" variant="eco" icon={Radar} onClick={() => navigate('/simulator')}>
              Sail it
            </Button>
          }
        >
          <div className="grid gap-5 sm:grid-cols-3">
            <div>
              <p className="text-faint mb-2 text-xs font-semibold uppercase tracking-wide">
                Fuel mix
              </p>
              <div className="space-y-2">
                {Object.entries(result.plan.fuel_mix ?? {}).map(([name, count]) => (
                  <MeterRow
                    key={name}
                    label={name}
                    value={count}
                    max={result.plan.assignments.length}
                    display={`${count}`}
                    tone="eco"
                  />
                ))}
              </div>
            </div>
            <div>
              <p className="text-faint mb-2 text-xs font-semibold uppercase tracking-wide">
                Cost breakdown
              </p>
              <div className="space-y-2">
                {Object.entries(result.plan.cost_breakdown ?? {}).map(([name, value]) => (
                  <MeterRow
                    key={name}
                    label={name.replace(/_usd$/, '').replace(/_/g, ' ')}
                    value={value}
                    max={Object.values(result.plan.cost_breakdown).reduce((a, b) => a + b, 0)}
                    display={usd(value, { compact: true })}
                  />
                ))}
              </div>
            </div>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between gap-2">
                <dt className="text-faint">Mean speed</dt>
                <dd className="numeric">{num(result.plan.average_speed_knots, 2)} kn</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-faint">Mean shore power</dt>
                <dd className="numeric">{pct(result.plan.average_shore_power_pct)}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-faint">Pareto front</dt>
                <dd className="numeric">{result.pareto_size ?? 1}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-faint">Constraints</dt>
                <dd>
                  <Badge tone={result.feasible ? 'eco' : 'danger'}>
                    {result.feasible ? 'satisfied' : 'violated'}
                  </Badge>
                </dd>
              </div>
            </dl>
          </div>
        </Card>
      )}

      {/* Solver roster */}
      <Card
        className="mt-5"
        title="Solvers"
        description="Two quantum-inspired, two classical baselines. The baselines are there to be beaten in public, not hidden."
      >
        {algorithms.loading ? (
          <Skeleton className="h-32 w-full" />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {(algorithms.data ?? []).map((a) => (
              <div
                key={a.id}
                className={cx(
                  'rounded-lg border p-4',
                  a.quantum_inspired && 'bg-primary-50/40 dark:bg-primary-950/20',
                )}
                style={{ borderColor: 'rgb(var(--border-subtle))' }}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-semibold">{a.name}</p>
                  <Badge tone={a.quantum_inspired ? 'primary' : 'neutral'}>
                    {a.quantum_inspired ? 'quantum-inspired' : 'classical'}
                  </Badge>
                  {a.multi_objective && <Badge tone="eco">multi-objective</Badge>}
                </div>
                <p className="text-faint mt-1.5 text-sm">{a.description}</p>
              </div>
            ))}
          </div>
        )}
        <Alert tone="info" className="mt-4" title="To be clear about the word quantum">
          These run on ordinary hardware. QPSO samples particle positions from a delta potential
          well instead of using velocity; QGA carries chromosomes as qubit registers updated by
          rotation gates. That is quantum-<em>inspired</em>. The vessel-to-lane assignment is a
          QUBO, so running it on real annealing hardware is a roadmap item, not a claim we make
          today.
        </Alert>
      </Card>

      {/* Jump-off */}
      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ['Live simulator', '/simulator', Radar, 'Watch the plan sail'],
          ['Fuel prediction', '/predict', Activity, 'What a voyage will burn'],
          ['Fleet & lanes', '/fleet', Ship, '20 vessels, 16 lanes'],
          ['Benchmarks', '/benchmarks', Target, 'Evidence for the claims'],
        ].map(([label, path, Icon, blurb]) => (
          <Link
            key={path}
            to={path}
            className="card flex items-center gap-3 p-4 transition-shadow hover:shadow-card-hover"
          >
            <span className="rounded-lg bg-[rgb(var(--surface-sunken))] p-2.5">
              <Icon size={18} className="text-primary-600 dark:text-primary-400" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{label}</span>
              <span className="text-faint block truncate text-xs">{blurb}</span>
            </span>
            <ArrowRight size={16} className="text-faint shrink-0" aria-hidden />
          </Link>
        ))}
      </div>

      <p className="text-faint mt-5 flex items-center justify-center gap-2 text-xs">
        <BookOpen size={13} aria-hidden />
        Every figure on this page came from a live call to the API — there are no fixtures in this
        build.
      </p>
    </>
  )
}
