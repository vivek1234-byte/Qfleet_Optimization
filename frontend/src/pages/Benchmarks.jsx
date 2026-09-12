/** Algorithm benchmarking — multi-seed comparison of quantum-inspired and classical solvers. */
import { BarChart3, ChevronDown, Gauge, HelpCircle, Play } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  Cell,
  ErrorBar,
  Line,
  LineChart,
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
  NumberInput,
  PageHeader,
  Skeleton,
} from '../components/ui'
import { useAsync, useFetch } from '../hooks/useApi'
import api from '../lib/api'
import { algorithmColor } from '../lib/domain'
import { num, seconds } from '../lib/format'

const ALL_ALGORITHMS = ['qpso', 'qga', 'pso', 'nsga2']
const EMPTY = []

export default function Benchmarks() {
  const algorithms = useFetch((signal) => api.optimization.algorithms({ signal }), [])
  const guide = useFetch((signal) => api.benchmarks.metricsGuide({ signal }), [])
  const stored = useFetch((signal) => api.benchmarks.results({ signal }), [])

  const bench = useAsync((signal, body) => api.benchmarks.run(body, { signal }))
  const scalability = useAsync((signal, body) => api.benchmarks.scalability(body, { signal }))

  const [config, setConfig] = useState({
    algorithms: [...ALL_ALGORITHMS],
    n_runs: 5,
    n_vessels: 10,
    n_routes: 6,
    max_iterations: 100,
    population_size: 40,
    seed: 1000,
  })

  const setNumber = (key) => (event) =>
    setConfig((c) => ({ ...c, [key]: Number(event.target.value) }))

  const runBenchmark = useCallback(() => {
    bench.run({ ...config })
    // bench is a stable useAsync handle
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config])

  const runScalability = useCallback(() => {
    scalability.run({
      algorithms: config.algorithms,
      problem_sizes: [5, 10, 20, 35],
      n_runs: 2,
      max_iterations: 60,
      population_size: 30,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.algorithms])

  // The freshest thing we have: this session's run, else whatever the backend
  // still has from a previous one.
  const report = bench.data ?? (stored.data?.status === 'completed' ? stored.data : null)
  const results = report?.results ?? EMPTY

  const fitnessData = useMemo(
    () =>
      results.map((row) => ({
        name: row.algorithm.toUpperCase(),
        algorithm: row.algorithm,
        mean: row.best_fitness_mean,
        std: row.best_fitness_std,
        min: row.best_fitness_min,
        quantum: row.quantum_inspired,
      })),
    [results],
  )

  const timeData = useMemo(
    () =>
      results.map((row) => ({
        name: row.algorithm.toUpperCase(),
        algorithm: row.algorithm,
        time: row.time_seconds_mean,
        evaluations: row.evaluations_mean,
      })),
    [results],
  )

  const convergenceSeries = useMemo(() => {
    const conv = report?.convergence ?? {}
    const ids = Object.keys(conv)
    if (!ids.length) return []
    const length = Math.max(...ids.map((id) => conv[id].length))
    return Array.from({ length }, (_, i) => {
      const row = { iteration: i + 1 }
      ids.forEach((id) => {
        row[id] = conv[id][i]
      })
      return row
    })
  }, [report])

  const scalabilityData = useMemo(() => {
    const raw = scalability.data
    if (!raw) return []
    // The endpoint returns one row per (algorithm, size); pivot to one row per
    // size so every algorithm can be a line on the same axes.
    const bySize = new Map()
    ;(raw.rows ?? []).forEach((row) => {
      const size = row.problem_size
      if (!bySize.has(size)) bySize.set(size, { size })
      bySize.get(size)[row.algorithm] = row.time_seconds
    })
    return [...bySize.values()].sort((a, b) => a.size - b.size)
  }, [scalability.data])

  const winner = results.find((r) => r.algorithm === report?.winner)
  const quantumBest = results
    .filter((r) => r.quantum_inspired)
    .sort((a, b) => a.best_fitness_mean - b.best_fitness_mean)[0]
  const classicalBest = results
    .filter((r) => !r.quantum_inspired)
    .sort((a, b) => a.best_fitness_mean - b.best_fitness_mean)[0]

  return (
    <>
      <PageHeader title="Benchmarks" description="Which solver performs best." />

      <div className="mx-auto max-w-xl">
        {bench.error && <ErrorState error={bench.error} onRetry={runBenchmark} className="mb-5" />}

        {bench.loading ? (
          <Skeleton className="h-32 w-full rounded-xl" />
        ) : winner ? (
          <>
            <h2 className="text-faint text-xs font-semibold uppercase tracking-wide">
              Algorithm performance
            </h2>
            <dl
              className="mt-3 divide-y text-base"
              style={{ borderColor: 'rgb(var(--border-subtle))' }}
            >
              {[
                ['Best solver', winner.algorithm.toUpperCase()],
                // The backend has no "solution quality" figure; the scalarised
                // objective is what it ranks solvers on. Lower is better.
                ['Scalarised objective', num(winner.best_fitness_mean, 4)],
                ['Runtime', seconds(winner.time_seconds_mean)],
              ].map(([label, value]) => (
                <div key={label} className="flex items-baseline justify-between gap-4 py-3">
                  <dt className="text-faint text-sm">{label}</dt>
                  <dd className="numeric font-semibold">{value}</dd>
                </div>
              ))}
            </dl>
          </>
        ) : (
          <EmptyState
            icon={BarChart3}
            title="No benchmark run yet"
            description="Configure solvers and fleet size in Technical details, then run."
            action={
              <Button icon={Play} onClick={runBenchmark}>
                Run benchmark
              </Button>
            }
          />
        )}
      </div>

      <details
        className="group mt-10 rounded-lg border"
        style={{ borderColor: 'rgb(var(--border-subtle))' }}
      >
        <summary className="expand-toggle cursor-pointer list-none [&::-webkit-details-marker]:hidden">
          Technical details
          <ChevronDown
            size={14}
            className="text-faint transition-transform group-open:rotate-180"
            aria-hidden
          />
        </summary>
        <div
          className="space-y-5 border-t p-4"
          style={{ borderColor: 'rgb(var(--border-subtle))' }}
        >
          <Card title="Benchmark setup">
            <div className="space-y-4">
              <div>
                <p className="field-label">Solvers</p>
                <div className="space-y-1.5">
                  {(algorithms.data ?? []).map((a) => (
                    <Checkbox
                      key={a.id}
                      label={a.name}
                      hint={a.quantum_inspired ? 'quantum-inspired' : 'classical baseline'}
                      checked={config.algorithms.includes(a.id)}
                      onChange={(e) =>
                        setConfig((c) => ({
                          ...c,
                          algorithms: e.target.checked
                            ? [...c.algorithms, a.id]
                            : c.algorithms.filter((x) => x !== a.id),
                        }))
                      }
                    />
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <NumberInput
                  label="Runs per solver"
                  min={1}
                  max={30}
                  value={config.n_runs}
                  onChange={setNumber('n_runs')}
                />
                <NumberInput
                  label="Base seed"
                  min={0}
                  value={config.seed}
                  onChange={setNumber('seed')}
                />
                <NumberInput
                  label="Vessels"
                  min={2}
                  max={60}
                  value={config.n_vessels}
                  onChange={setNumber('n_vessels')}
                />
                <NumberInput
                  label="Routes"
                  min={1}
                  max={16}
                  value={config.n_routes}
                  onChange={setNumber('n_routes')}
                />
                <NumberInput
                  label="Iterations"
                  min={10}
                  max={500}
                  step={10}
                  value={config.max_iterations}
                  onChange={setNumber('max_iterations')}
                />
                <NumberInput
                  label="Population"
                  min={10}
                  max={200}
                  step={10}
                  value={config.population_size}
                  onChange={setNumber('population_size')}
                />
              </div>

              <Alert tone="warning">
                {config.algorithms.length} solvers × {config.n_runs} runs ={' '}
                {config.algorithms.length * config.n_runs} optimisations.
              </Alert>

              <Button
                className="w-full"
                icon={Play}
                loading={bench.loading}
                disabled={!config.algorithms.length}
                onClick={runBenchmark}
              >
                Run benchmark
              </Button>
              <Button
                className="w-full"
                variant="secondary"
                icon={Gauge}
                loading={scalability.loading}
                onClick={runScalability}
              >
                Scalability sweep
              </Button>
            </div>
          </Card>

          {report && (
            <>
              <dl
                className="divide-y text-sm"
                style={{ borderColor: 'rgb(var(--border-subtle))' }}
              >
                {[
                  [
                    'Best quantum',
                    quantumBest ? num(quantumBest.best_fitness_mean, 4) : '—',
                    quantumBest?.algorithm?.toUpperCase(),
                  ],
                  [
                    'Best classical',
                    classicalBest ? num(classicalBest.best_fitness_mean, 4) : '—',
                    classicalBest?.algorithm?.toUpperCase(),
                  ],
                  [
                    'Wall time',
                    seconds(report.wall_time_seconds),
                    `${report.config?.n_runs} runs each`,
                  ],
                ].map(([label, value, hint]) => (
                  <div key={label} className="flex items-baseline justify-between gap-4 py-2.5">
                    <dt className="text-faint">
                      {label}
                      {hint && <span className="ml-2 text-xs">{hint}</span>}
                    </dt>
                    <dd className="numeric">{value}</dd>
                  </div>
                ))}
              </dl>

              {report.summary && <Alert tone="info">{report.summary}</Alert>}

              <Card
                title="Mean objective (lower is better)"
                description="Whiskers show one standard deviation across seeds."
              >
                <ChartFrame height={300}>
                  <BarChart data={fitnessData} margin={{ top: 16, right: 16, bottom: 10, left: 0 }}>
                    <ThemedGrid />
                    <ThemedXAxis dataKey="name" />
                    <ThemedYAxis
                      domain={['auto', 'auto']}
                      tickFormatter={(v) => v.toFixed(3)}
                      width={70}
                    />
                    <ThemedTooltip formatter={(v) => (typeof v === 'number' ? v.toFixed(6) : v)} />
                    <Bar dataKey="mean" name="Mean objective" radius={[4, 4, 0, 0]}>
                      {fitnessData.map((row) => (
                        <Cell key={row.algorithm} fill={algorithmColor(row.algorithm)} />
                      ))}
                      <ErrorBar dataKey="std" width={6} strokeWidth={1.5} stroke="#94a3b8" />
                    </Bar>
                  </BarChart>
                </ChartFrame>
                <p className="text-faint mt-3 text-xs">
                  Overlapping error bars indicate the difference is not statistically significant.
                </p>
              </Card>

              {convergenceSeries.length > 0 && (
                <Card title="Mean convergence" description="Averaged across runs">
                  <ChartFrame height={320}>
                    <LineChart
                      data={convergenceSeries}
                      margin={{ top: 10, right: 20, bottom: 46, left: 0 }}
                    >
                      <ThemedGrid />
                      <ThemedXAxis
                        dataKey="iteration"
                        label={{
                          value: 'Iteration',
                          position: 'insideBottom',
                          offset: -26,
                          fontSize: 12,
                        }}
                      />
                      <ThemedYAxis tickFormatter={(v) => v.toFixed(3)} width={70} />
                      <ThemedTooltip formatter={(v) => (typeof v === 'number' ? v.toFixed(6) : v)} />
                      <ThemedLegend />
                      {Object.keys(report.convergence ?? {}).map((id) => (
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

              <div className="grid gap-5 lg:grid-cols-2">
                <Card title="Cost of a run" description="Mean wall time per optimisation">
                  <ChartFrame height={250}>
                    <BarChart data={timeData} margin={{ top: 10, right: 16, bottom: 10, left: 0 }}>
                      <ThemedGrid />
                      <ThemedXAxis dataKey="name" />
                      <ThemedYAxis unit=" s" width={60} />
                      <ThemedTooltip formatter={(v) => seconds(v)} />
                      <Bar dataKey="time" name="Seconds" radius={[4, 4, 0, 0]}>
                        {timeData.map((row) => (
                          <Cell key={row.algorithm} fill={algorithmColor(row.algorithm)} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ChartFrame>
                </Card>

                <Card
                  title="Scalability"
                  description="How run time grows with fleet size"
                  actions={
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={scalability.loading}
                      onClick={runScalability}
                    >
                      Run sweep
                    </Button>
                  }
                >
                  {scalability.error ? (
                    <ErrorState error={scalability.error} onRetry={runScalability} />
                  ) : scalability.loading ? (
                    <Skeleton className="h-56 w-full" />
                  ) : scalabilityData.length ? (
                    <ChartFrame height={250}>
                      <LineChart
                        data={scalabilityData}
                        margin={{ top: 10, right: 16, bottom: 18, left: 0 }}
                      >
                        <ThemedGrid />
                        <ThemedXAxis
                          dataKey="size"
                          label={{
                            value: 'Vessels',
                            position: 'insideBottom',
                            offset: -12,
                            fontSize: 12,
                          }}
                        />
                        <ThemedYAxis unit=" s" width={60} />
                        <ThemedTooltip formatter={(v) => seconds(v)} />
                        <ThemedLegend />
                        {config.algorithms.map((id) => (
                          <Line
                            key={id}
                            type="monotone"
                            dataKey={id}
                            name={id.toUpperCase()}
                            stroke={algorithmColor(id)}
                            strokeWidth={2}
                            dot={{ r: 3 }}
                          />
                        ))}
                      </LineChart>
                    </ChartFrame>
                  ) : (
                    <p className="text-faint py-12 text-center text-sm">
                      Run the sweep to see how each solver scales.
                    </p>
                  )}
                </Card>
              </div>

              <Card title="Full results" description={`Problem: ${report.problem?.n_dimensions} decision variables`}>
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
                    {
                      key: 'best_fitness_mean',
                      header: 'Mean',
                      align: 'right',
                      help: 'Normalised weighted objective, lower is better',
                      render: (r) => r.best_fitness_mean?.toFixed(6),
                    },
                    {
                      key: 'best_fitness_std',
                      header: 'Std dev',
                      align: 'right',
                      render: (r) => r.best_fitness_std?.toFixed(6),
                    },
                    {
                      key: 'best_fitness_min',
                      header: 'Best run',
                      align: 'right',
                      render: (r) => r.best_fitness_min?.toFixed(6),
                    },
                    {
                      key: 'hypervolume_mean',
                      header: 'Hypervolume',
                      align: 'right',
                      help: 'Volume of objective space dominated — higher is better',
                      render: (r) =>
                        Number.isFinite(r.hypervolume_mean)
                          ? r.hypervolume_mean.toExponential(3)
                          : '—',
                    },
                    {
                      key: 'time_seconds_mean',
                      header: 'Time',
                      align: 'right',
                      render: (r) => seconds(r.time_seconds_mean),
                    },
                    {
                      key: 'evaluations_mean',
                      header: 'Evals',
                      align: 'right',
                      render: (r) => num(r.evaluations_mean),
                    },
                    {
                      key: 'feasible_runs',
                      header: 'Feasible',
                      align: 'right',
                      render: (r) => `${r.feasible_runs}/${r.n_runs}`,
                    },
                  ]}
                  rows={results}
                  getRowKey={(row) => row.algorithm}
                  highlightRow={(row) => row.algorithm === report.winner}
                />
              </Card>
            </>
          )}

          <Card
            title="What the metrics mean"
            description="Definitions for each reported metric"
            actions={<HelpCircle size={16} className="text-faint" aria-hidden />}
          >
            {guide.loading ? (
              <Skeleton className="h-40 w-full" />
            ) : guide.error ? (
              <ErrorState error={guide.error} onRetry={guide.refetch} />
            ) : (
              <dl className="space-y-3">
                {(guide.data ?? []).map((metric) => (
                  <div key={metric.id}>
                    <dt className="flex flex-wrap items-baseline gap-2 text-sm font-medium">
                      {metric.name}
                      <Badge tone="neutral">{metric.direction}</Badge>
                    </dt>
                    <dd className="text-faint mt-0.5 text-sm">{metric.description}</dd>
                  </div>
                ))}
              </dl>
            )}
          </Card>
        </div>
      </details>
    </>
  )
}
