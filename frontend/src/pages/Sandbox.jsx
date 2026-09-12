/**
 * What-if sandbox — move a lever, watch the solver re-run live via SSE,
 * and diff each result against the previous one.
 */
import {
  Activity,
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Coins,
  Droplets,
  Gauge,
  Leaf,
  Minus,
  RotateCcw,
  Sparkles,
  Square,
  Waves,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Cell, Line, LineChart, Scatter, ScatterChart, ZAxis } from 'recharts'

import {
  ChartFrame,
  ThemedGrid,
  ThemedTooltip,
  ThemedXAxis,
  ThemedYAxis,
} from '../components/charts'
import {
  Alert,
  Badge,
  Button,
  Card,
  DataTable,
  ErrorState,
  NumberInput,
  PageHeader,
  RangeInput,
  Select,
  cx,
} from '../components/ui'
import { useFetch } from '../hooks/useApi'
import api, { streamOptimization } from '../lib/api'
import {
  MONTHS,
  SANDBOX_DEFAULTS,
  algorithmColor,
  ciiColor,
  fuelColor,
  seasonColor,
} from '../lib/domain'
import { compact, num, pct, seconds, signedPct, usd } from '../lib/format'
import { setActivePlan } from '../lib/planStore'

const EMPTY = []

const OBJECTIVES = [
  { key: 'fuel_consumption_tons', label: 'Fuel', icon: Droplets, unit: 't', accent: '#06a3ee' },
  { key: 'co2_emissions_tons', label: 'CO₂e', icon: Leaf, unit: 't', accent: '#15af73' },
  { key: 'operational_cost_usd', label: 'Cost', icon: Coins, unit: '', accent: '#f59e0b' },
]

const formatObjective = (key, value) =>
  key === 'operational_cost_usd' ? usd(value, { compact: true }) : `${compact(value)} t`

/* -------------------------------------------------------------------------- */
/* Pieces                                                                      */
/* -------------------------------------------------------------------------- */
function DeltaStat({ objective, current, previous }) {
  const value = current?.[objective.key]
  const before = previous?.[objective.key]
  const delta =
    Number.isFinite(value) && Number.isFinite(before) && before !== 0
      ? ((value - before) / before) * 100
      : null

  const Arrow = delta === null ? Minus : delta < -0.05 ? ArrowDown : delta > 0.05 ? ArrowUp : Minus
  // Every objective here is minimised, so down is always the good direction.
  const tone =
    delta === null || Math.abs(delta) <= 0.05
      ? 'text-faint'
      : delta < 0
        ? 'text-eco-600 dark:text-eco-400'
        : 'text-rose-600 dark:text-rose-400'

  // With nothing to compare against, the headline is the figure itself. The
  // old version showed a dash next to a Minus icon, which read as two dashes
  // and looked like a rendering fault rather than a first run.
  return (
    <div className="min-w-0">
      <p className="text-faint text-xs font-medium uppercase tracking-wide">{objective.label}</p>
      {delta === null ? (
        <p className="numeric mt-1 text-3xl font-semibold tracking-tight">
          {Number.isFinite(value) ? formatObjective(objective.key, value) : '—'}
        </p>
      ) : (
        <p
          className={cx(
            'numeric mt-1 flex items-center gap-1 text-3xl font-semibold tracking-tight',
            tone,
          )}
        >
          <Arrow size={24} aria-hidden />
          {pct(Math.abs(delta), 1)}
        </p>
      )}
      <p className="text-faint numeric mt-1 text-xs">
        {delta === null
          ? 'Move a lever to compare'
          : `${Number.isFinite(value) ? formatObjective(objective.key, value) : '—'} · ${signedPct(delta)} vs last run`}
      </p>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */
export default function Sandbox() {
  const algorithms = useFetch((signal) => api.optimization.algorithms({ signal }), [])
  const seasonality = useFetch((signal) => api.regulatory.seasonality({ signal }), [])

  const [config, setConfig] = useState(SANDBOX_DEFAULTS)
  const [status, setStatus] = useState('idle') // idle | running | done | error
  const [progress, setProgress] = useState(EMPTY)
  const [result, setResult] = useState(null)
  const [previous, setPrevious] = useState(null)
  const [error, setError] = useState(null)
  const [autoRun, setAutoRun] = useState(true)

  const closeRef = useRef(null)
  const runIdRef = useRef(0)
  // The last completed result, kept in a ref the effect owns so `run` can read
  // it without listing `result` as a dependency — which would restart the
  // stream every time a run finished.
  const resultRef = useRef(null)
  useEffect(() => {
    resultRef.current = result
  }, [result])

  /* ---- the run ---------------------------------------------------------- */
  const run = useCallback(() => {
    closeRef.current?.()
    const runId = (runIdRef.current += 1)
    // Keep the last completed run as the comparison point, not whatever a
    // half-finished stream left behind.
    setPrevious(resultRef.current)
    setProgress(EMPTY)
    setError(null)
    setStatus('running')

    closeRef.current = streamOptimization(
      {
        algorithm: config.algorithm,
        n_vessels: config.n_vessels,
        n_routes: config.n_routes,
        max_iterations: config.max_iterations,
        population_size: config.population_size,
        carbon_price_usd_per_ton: config.carbon_price_usd_per_ton,
        seed: config.seed,
        month: config.month,
        speed_cap_knots: config.speed_cap_knots,
      },
      {
        onProgress: (event) => {
          if (runIdRef.current !== runId) return
          setProgress((rows) => [...rows, { iteration: event.iteration, value: event.value }])
        },
        onDone: (payload) => {
          if (runIdRef.current !== runId) return
          setResult(payload)
          setStatus('done')
        },
        onError: (payload) => {
          if (runIdRef.current !== runId) return
          setError(payload)
          setStatus('error')
        },
      },
    )
  }, [config])

  // Close the stream on unmount, or the browser holds the connection — and the
  // solver thread behind it — open after the user has navigated away.
  useEffect(() => () => closeRef.current?.(), [])

  // Auto-run on a settled change. Debounced, because dragging a slider fires
  // a change per pixel and each one would start a solver.
  useEffect(() => {
    if (!autoRun) return undefined
    const id = setTimeout(run, 350)
    return () => clearTimeout(id)
  }, [autoRun, run])

  const stop = useCallback(() => {
    runIdRef.current += 1
    closeRef.current?.()
    setStatus('idle')
  }, [])

  const reset = useCallback(() => {
    setConfig(SANDBOX_DEFAULTS)
    setPrevious(null)
  }, [])

  const set = (key) => (value) => setConfig((c) => ({ ...c, [key]: value }))

  /* ---- derived ---------------------------------------------------------- */
  const percent = progress.length
    ? Math.min(100, (progress[progress.length - 1].iteration / config.max_iterations) * 100)
    : 0

  const paretoPoints = useMemo(() => {
    const front = result?.pareto_front ?? EMPTY
    return front.map((p, i) => ({
      index: i,
      fuel: p.fuel_consumption_tons,
      co2: p.co2_emissions_tons,
      cost: p.operational_cost_usd,
      feasible: p.feasible,
    }))
  }, [result])

  const previousPareto = useMemo(() => {
    const front = previous?.pareto_front ?? EMPTY
    return front.map((p, i) => ({
      index: i,
      fuel: p.fuel_consumption_tons,
      co2: p.co2_emissions_tons,
      cost: p.operational_cost_usd,
    }))
  }, [previous])

  const planDiff = useMemo(() => {
    const now = result?.plan?.assignments
    const before = previous?.plan?.assignments
    if (!now?.length) return EMPTY
    const beforeByVessel = Object.fromEntries((before ?? EMPTY).map((a) => [a.vessel_name, a]))
    return now
      .map((a) => {
        const was = beforeByVessel[a.vessel_name]
        return {
          ...a,
          changedRoute: was && was.route_name !== a.route_name ? was.route_name : null,
          changedFuel: was && was.fuel_type !== a.fuel_type ? was.fuel_type : null,
          speedDelta: was ? a.speed_knots - was.speed_knots : null,
        }
      })
      .sort((a, b) => {
        const score = (r) => (r.changedFuel ? 2 : 0) + (r.changedRoute ? 2 : 0) + Math.abs(r.speedDelta ?? 0)
        return score(b) - score(a)
      })
  }, [result, previous])

  const changedCount = planDiff.filter((r) => r.changedRoute || r.changedFuel).length

  const seasonFactor = result?.plan?.season?.mean_factor
  const cii = result?.plan?.compliance?.cii
  const laneProfiles = seasonality.data?.lanes ?? EMPTY

  const monthCurve = useMemo(() => {
    if (!laneProfiles.length) return EMPTY
    // Mean across every lane: what the whole network's weather does over a year.
    return Array.from({ length: 12 }, (_, i) => {
      const values = laneProfiles.map((l) => l.monthly[i]?.factor ?? 1)
      return {
        month: MONTHS[i].short,
        monthValue: i + 1,
        factor: values.reduce((a, b) => a + b, 0) / values.length,
      }
    })
  }, [laneProfiles])

  const running = status === 'running'
  // The month lever is a slider here; 0 is the "annual mean" end of the range,
  // which is the same empty value the stream treats as "no month".
  const monthValue = config.month === '' ? 0 : Number(config.month)

  return (
    <>
      <PageHeader title="What-if Sandbox" description="Change a lever, see the impact." />

      {error && (
        <ErrorState
          error={{ message: error.message ?? 'The solver stream failed.', code: error.code }}
          onRetry={run}
          className="mb-5"
        />
      )}

      {/* The three levers. Every change still re-solves on its own. */}
      <div className="grid gap-x-10 gap-y-6 sm:grid-cols-3">
        <RangeInput
          label="Carbon price"
          unit=" $/t"
          min={0}
          max={300}
          step={10}
          value={config.carbon_price_usd_per_ton}
          onChange={(e) => set('carbon_price_usd_per_ton')(Number(e.target.value))}
        />
        {/* The top of the range means "no cap", which reads better
            as the word than as 22 kn — no vessel here exceeds it. */}
        <RangeInput
          label="Speed cap"
          unit={config.speed_cap_knots === '' ? '' : ' kn'}
          min={9}
          max={22}
          step={0.5}
          value={config.speed_cap_knots === '' ? 22 : config.speed_cap_knots}
          displayValue={config.speed_cap_knots === '' ? 'No cap' : undefined}
          onChange={(e) => {
            const v = Number(e.target.value)
            set('speed_cap_knots')(v >= 22 ? '' : v)
          }}
        />
        <RangeInput
          label="Season"
          min={0}
          max={12}
          step={1}
          value={monthValue}
          displayValue={monthValue === 0 ? 'Annual mean' : MONTHS[monthValue - 1].label}
          onChange={(e) => {
            const v = Number(e.target.value)
            set('month')(v === 0 ? '' : String(v))
          }}
        />
      </div>

      {/* The impact, against the previous run */}
      <div className="mt-9 flex flex-wrap items-start gap-x-14 gap-y-6">
        {OBJECTIVES.map((objective) => (
          <DeltaStat
            key={objective.key}
            objective={objective}
            current={result?.best_objectives}
            previous={previous?.best_objectives}
          />
        ))}
      </div>

      <div className="mb-8 mt-7">
        {running ? (
          <Button variant="secondary" icon={Square} onClick={stop}>
            Stop
          </Button>
        ) : (
          <Button icon={Sparkles} onClick={run}>
            Recalculate
          </Button>
        )}
      </div>

      <details className="group">
        <summary className="expand-toggle cursor-pointer list-none [&::-webkit-details-marker]:hidden">
          Technical details
          <ChevronDown
            size={14}
            className="text-faint transition-transform group-open:rotate-180"
            aria-hidden
          />
        </summary>
        <div className="grid gap-5 pt-4 xl:grid-cols-[21rem_minmax(0,1fr)]">
          {/* The rest of the levers */}
          <div className="xl:sticky xl:top-20 xl:self-start">
            <Card title="Levers" description="Every change re-solves the problem">
              <div className="space-y-5">
                <Select
                  label="Algorithm"
                  value={config.algorithm}
                  onChange={(e) => set('algorithm')(e.target.value)}
                  options={(algorithms.data ?? EMPTY).map((a) => ({ value: a.id, label: a.name }))}
                />

                <div className="grid grid-cols-2 gap-3">
                  <NumberInput
                    label="Vessels"
                    min={2}
                    max={30}
                    value={config.n_vessels}
                    onChange={(e) => set('n_vessels')(Number(e.target.value))}
                  />
                  <NumberInput
                    label="Routes"
                    min={1}
                    max={16}
                    value={config.n_routes}
                    onChange={(e) => set('n_routes')(Number(e.target.value))}
                  />
                  <NumberInput
                    label="Iterations"
                    min={10}
                    max={400}
                    step={10}
                    value={config.max_iterations}
                    onChange={(e) => set('max_iterations')(Number(e.target.value))}
                  />
                  <NumberInput
                    label="Population"
                    min={10}
                    max={120}
                    step={10}
                    value={config.population_size}
                    onChange={(e) => set('population_size')(Number(e.target.value))}
                  />
                </div>

                <label className="flex items-start gap-2.5 text-sm">
                  <input
                    type="checkbox"
                    checked={autoRun}
                    onChange={(e) => setAutoRun(e.target.checked)}
                    className="mt-0.5 h-4 w-4 cursor-pointer rounded border-[rgb(var(--border-strong))] accent-primary-600"
                  />
                  <span>
                    Re-solve automatically
                    <span className="text-faint block text-xs">
                      Debounced — one run per change, not per pixel.
                    </span>
                  </span>
                </label>

                <Button className="w-full" variant="ghost" icon={RotateCcw} onClick={reset}>
                  Reset levers
                </Button>

                {result && (
                  <Button
                    className="w-full"
                    variant="eco"
                    onClick={() => setActivePlan(result, 'sandbox')}
                  >
                    Send this plan to the simulator
                  </Button>
                )}
              </div>
            </Card>
          </div>

          {/* Results */}
          <div className="min-w-0 space-y-5">
            {/* Progress */}
            <Card
              title="Solver"
              description={
                running
                  ? `Iteration ${progress.length} of ${config.max_iterations}`
                  : result
                    ? `${seconds(result.elapsed_seconds)} · ${num(result.n_evaluations)} evaluations`
                    : 'Idle'
              }
              actions={
                <Badge tone={running ? 'primary' : status === 'error' ? 'danger' : 'eco'}>
                  {running ? 'streaming' : status === 'error' ? 'failed' : result ? 'done' : 'ready'}
                </Badge>
              }
            >
              <div className="h-1.5 overflow-hidden rounded-full bg-[rgb(var(--surface-sunken))]">
                <div
                  className="h-full rounded-full transition-[width] duration-150"
                  style={{
                    width: `${running ? percent : result ? 100 : 0}%`,
                    backgroundColor: algorithmColor(config.algorithm),
                  }}
                />
              </div>

              <ChartFrame height={220}>
                <LineChart
                  data={progress}
                  margin={{ top: 14, right: 16, bottom: 22, left: 0 }}
                >
                  <ThemedGrid />
                  <ThemedXAxis
                    dataKey="iteration"
                    type="number"
                    domain={[1, config.max_iterations]}
                    allowDecimals={false}
                    label={{
                      value: 'Iteration',
                      position: 'insideBottom',
                      offset: -14,
                      fontSize: 12,
                    }}
                  />
                  <ThemedYAxis
                    domain={['auto', 'auto']}
                    tickFormatter={(v) => v.toFixed(3)}
                    width={70}
                  />
                  <ThemedTooltip formatter={(v) => v.toFixed(6)} />
                  <Line
                    type="monotone"
                    dataKey="value"
                    name="Objective"
                    stroke={algorithmColor(config.algorithm)}
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ChartFrame>
              <p className="text-faint text-xs">
                Normalised weighted objective, one point per SSE iteration.
              </p>
            </Card>

            {/* Conditions in force */}
            {result && (
              <div className="card flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3 text-sm">
                <span className="inline-flex items-center gap-2 font-medium">
                  <Activity size={15} aria-hidden />
                  {result.algorithm_name}
                </span>
                {result.plan?.season && (
                  <span className="inline-flex items-center gap-1.5">
                    <Waves size={14} aria-hidden style={{ color: seasonColor(seasonFactor) }} />
                    {result.plan.season.label}
                    {seasonFactor !== 1 && (
                      <span className="numeric text-faint">
                        (sea state ×{seasonFactor.toFixed(2)})
                      </span>
                    )}
                  </span>
                )}
                {config.speed_cap_knots !== '' && (
                  <span className="inline-flex items-center gap-1.5">
                    <Gauge size={14} aria-hidden /> capped at {config.speed_cap_knots} kn
                  </span>
                )}
                {config.carbon_price_usd_per_ton > 0 && (
                  <span className="inline-flex items-center gap-1.5">
                    <Coins size={14} aria-hidden /> carbon at ${config.carbon_price_usd_per_ton}/t
                  </span>
                )}
                {cii && (
                  <span className="inline-flex items-center gap-1.5">
                    CII
                    {['A', 'B', 'C', 'D', 'E'].map((band) => (
                      <span
                        key={band}
                        className="grid h-4 w-4 place-items-center rounded text-[0.6rem] font-bold text-white"
                        style={{
                          backgroundColor: ciiColor(band),
                          opacity: cii.distribution[band] ? 1 : 0.18,
                        }}
                        title={`${cii.distribution[band] ?? 0} rated ${band}`}
                      >
                        {cii.distribution[band] || ''}
                      </span>
                    ))}
                  </span>
                )}
                <Badge tone={result.feasible ? 'eco' : 'danger'}>
                  {result.feasible ? 'feasible' : 'constraint violation'}
                </Badge>
              </div>
            )}

            {/* Pareto, now vs before */}
            {paretoPoints.length > 0 && (
              <Card
                title="Trade-off surface"
                description="Filled = current run, hollow = previous run."
              >
                <ChartFrame height={300}>
                  <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
                    <ThemedGrid vertical />
                    <ThemedXAxis
                      type="number"
                      dataKey="fuel"
                      name="Fuel"
                      unit=" t"
                      domain={['dataMin - 40', 'dataMax + 40']}
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
                      domain={['dataMin - 60', 'dataMax + 60']}
                      tickFormatter={(v) => num(v, 0)}
                      width={72}
                    />
                    <ZAxis type="number" dataKey="cost" range={[70, 380]} name="Cost" />
                    <ThemedTooltip
                      formatter={(value, name) => (name === 'Cost' ? usd(value) : `${num(value, 1)} t`)}
                    />
                    {previousPareto.length > 0 && (
                      <Scatter
                        data={previousPareto}
                        name="Previous"
                        fill="none"
                        stroke="#94a3b8"
                        strokeWidth={1.5}
                        isAnimationActive={false}
                      />
                    )}
                    <Scatter data={paretoPoints} name="Current" isAnimationActive={false}>
                      {paretoPoints.map((p) => (
                        <Cell key={p.index} fill={p.feasible ? '#06a3ee' : '#f43f5e'} />
                      ))}
                    </Scatter>
                  </ScatterChart>
                </ChartFrame>
              </Card>
            )}

            {/* Seasonal context */}
            {monthCurve.length > 0 && (
              <Card
                title="Network seasonality"
                description="Mean sea-state multiplier by month (indicative climatology)."
              >
                <ChartFrame height={200}>
                  <LineChart data={monthCurve} margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
                    <ThemedGrid />
                    <ThemedXAxis dataKey="month" />
                    <ThemedYAxis domain={[0.8, 1.3]} tickFormatter={(v) => `×${v.toFixed(1)}`} width={56} />
                    <ThemedTooltip formatter={(v) => `×${v.toFixed(3)}`} />
                    <Line
                      type="monotone"
                      dataKey="factor"
                      name="Sea state"
                      stroke="#38bdf8"
                      strokeWidth={2.5}
                      dot={(props) => {
                        const { cx: x, cy: y, payload } = props
                        return (
                          <circle
                            key={payload.monthValue}
                            cx={x}
                            cy={y}
                            r={config.month === String(payload.monthValue) ? 6 : 3.5}
                            fill={seasonColor(payload.factor)}
                            stroke="rgb(var(--surface-card))"
                            strokeWidth={1.5}
                          />
                        )
                      }}
                    />
                  </LineChart>
                </ChartFrame>
              </Card>
            )}

            {/* What actually changed */}
            {planDiff.length > 0 && (
              <Card
                title="Deployment plan"
                description={
                  previous
                    ? `${changedCount} of ${planDiff.length} vessels changed lane or fuel since the last run`
                    : `${planDiff.length} vessels · move a lever to see what changes`
                }
              >
                <DataTable
                  columns={[
                    { key: 'vessel_name', header: 'Vessel' },
                    {
                      key: 'route_name',
                      header: 'Lane',
                      render: (row) => (
                        <span>
                          {row.route_name}
                          {row.changedRoute && (
                            <span className="text-faint block text-xs line-through">
                              {row.changedRoute}
                            </span>
                          )}
                        </span>
                      ),
                    },
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
                          {row.changedFuel && (
                            <span className="text-faint text-xs line-through">{row.changedFuel}</span>
                          )}
                        </span>
                      ),
                    },
                    {
                      key: 'speed_knots',
                      header: 'Speed',
                      align: 'right',
                      render: (row) => (
                        <span>
                          {num(row.speed_knots, 2)} kn
                          {Number.isFinite(row.speedDelta) && Math.abs(row.speedDelta) > 0.05 && (
                            <span
                              className={cx(
                                'ml-1.5 text-xs',
                                row.speedDelta < 0
                                  ? 'text-eco-600 dark:text-eco-400'
                                  : 'text-amber-600 dark:text-amber-400',
                              )}
                            >
                              {row.speedDelta > 0 ? '+' : ''}
                              {row.speedDelta.toFixed(1)}
                            </span>
                          )}
                        </span>
                      ),
                    },
                    {
                      key: 'cii',
                      header: 'CII',
                      render: (row) =>
                        row.cii?.rated ? (
                          <span
                            className="grid h-5 w-5 place-items-center rounded text-[0.65rem] font-bold text-white"
                            style={{ backgroundColor: ciiColor(row.cii.rating) }}
                            title={`Attained ${row.cii.attained_cii} vs required ${row.cii.required_cii} gCO₂/dwt-nm`}
                          >
                            {row.cii.rating}
                          </span>
                        ) : (
                          '—'
                        ),
                    },
                    {
                      key: 'eca_fraction',
                      header: 'ECA',
                      align: 'right',
                      render: (row) =>
                        row.eca_fraction > 0 ? (
                          <span
                            className={cx(
                              'numeric',
                              row.eca_switch_share > 0 && 'text-amber-600 dark:text-amber-400',
                            )}
                            title={
                              row.eca_switch_share > 0
                                ? 'Has to switch to distillate inside the zone'
                                : 'Already burning a compliant fuel'
                            }
                          >
                            {pct(row.eca_fraction * 100, 0)}
                          </span>
                        ) : (
                          '—'
                        ),
                    },
                    {
                      key: 'fuel_tons',
                      header: 'Fuel',
                      align: 'right',
                      render: (row) => `${num(row.fuel_tons)} t`,
                    },
                    {
                      key: 'cost_usd',
                      header: 'Cost',
                      align: 'right',
                      render: (row) => usd(row.cost_usd, { compact: true }),
                    },
                  ]}
                  rows={planDiff}
                  getRowKey={(row) => `${row.vessel_id}-${row.route_id}`}
                  highlightRow={(row) => Boolean(row.changedRoute || row.changedFuel)}
                />
              </Card>
            )}

            {!result && !running && !error && (
              <Alert tone="info" title="Nothing solved yet">
                Move any lever or press <strong>Recalculate</strong> to start.
              </Alert>
            )}
          </div>
        </div>
      </details>
    </>
  )
}
