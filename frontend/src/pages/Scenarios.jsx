/**
 * Fuel-transition scenarios.
 *
 * The optimiser answers "how should we sail the fleet we have". This page
 * answers the question that follows: "what if we changed the fuel", with the
 * retrofit capex and the availability reality attached, because a scenario
 * that ignores those is not a plan.
 */
import {
  Battery,
  CalendarRange,
  Coins,
  Factory,
  Fuel,
  Leaf,
  Plug,
  TrendingDown,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Area,
  Bar,
  BarChart,
  ComposedChart,
  Line,
  Radar,
  RadarChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Cell,
} from 'recharts'

import {
  ChartFrame,
  ThemedGrid,
  ThemedLegend,
  ThemedTooltip,
  ThemedXAxis,
  ThemedYAxis,
  useChartTheme,
} from '../components/charts'
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  DataTable,
  ErrorState,
  NumberInput,
  PageHeader,
  RangeInput,
  Select,
  Skeleton,
  StatCard,
} from '../components/ui'
import { useAsync, useFetch } from '../hooks/useApi'
import api from '../lib/api'
import { FUEL_NOTES, fuelColor } from '../lib/domain'
import { compact, num, pct, signedPct, usd } from '../lib/format'

const TABS = [
  { id: 'compare', label: 'Compare fuels', icon: Fuel },
  { id: 'transition', label: 'Transition plan', icon: CalendarRange },
  { id: 'shore', label: 'Shore power', icon: Plug },
  { id: 'reference', label: 'Fuel reference', icon: Factory },
]

/* -------------------------------------------------------------------------- */
/* Compare                                                                     */
/* -------------------------------------------------------------------------- */
function CompareTab({ fuels, fleet }) {
  const compare = useAsync((signal, body) => api.scenarios.compare(body, { signal }))
  const [selected, setSelected] = useState(['LNG', 'Methanol', 'Ammonia'])
  const theme = useChartTheme()

  const run = useCallback(() => {
    if (selected.length) compare.run({ fuel_options: selected })
    // compare is a stable useAsync handle
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected])

  useEffect(() => {
    run()
    // Only on mount — re-running on every checkbox click would fire a request
    // per keystroke-equivalent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const scenarios = compare.data?.scenarios ?? []
  const base = scenarios.find((s) => s.scenario_name === 'Base Scenario')
  const alternatives = scenarios.filter((s) => s !== base)

  const chartData = scenarios.map((s) => ({
    name: s.fuel_type,
    co2: s.total_emissions_co2,
    cost: s.total_cost_usd,
    capex: s.retrofit_capex_usd,
    reduction: s.emission_reduction_pct,
  }))

  const radarData = useMemo(() => {
    if (!alternatives.length) return []
    const axes = [
      ['CO₂ cut', (s) => Math.max(s.emission_reduction_pct, 0) / 60],
      ['Cost saving', (s) => Math.max(-s.cost_change_pct, 0) / 40],
      ['Feasibility', (s) => s.feasibility],
      ['SOₓ cut', (s) => (base ? 1 - s.total_sox_tons / Math.max(base.total_sox_tons, 1) : 0)],
      ['NOₓ cut', (s) => (base ? 1 - s.total_nox_tons / Math.max(base.total_nox_tons, 1) : 0)],
      [
        'Capex ease',
        (s) => 1 - Math.min(s.retrofit_capex_usd / 120_000_000, 1),
      ],
    ]
    return axes.map(([axis, fn]) => {
      const row = { axis }
      alternatives.forEach((s) => {
        row[s.fuel_type] = Math.max(0, Math.min(1, fn(s))) * 100
      })
      return row
    })
  }, [alternatives, base])

  return (
    <div className="space-y-5">
      <Card
        title="Which fuels to evaluate"
        description={`Against the current fleet of ${fleet?.vessel_count ?? '—'} vessels`}
        actions={
          <Button size="sm" loading={compare.loading} onClick={run} disabled={!selected.length}>
            Compare
          </Button>
        }
      >
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {(fuels ?? []).map((fuel) => (
            <Checkbox
              key={fuel.name}
              label={fuel.name}
              hint={fuel.display_name}
              checked={selected.includes(fuel.name)}
              onChange={(e) =>
                setSelected((s) =>
                  e.target.checked ? [...s, fuel.name] : s.filter((n) => n !== fuel.name),
                )
              }
            />
          ))}
        </div>
      </Card>

      {compare.error && <ErrorState error={compare.error} onRetry={run} />}
      {compare.loading && <Skeleton className="h-72 w-full rounded-xl" />}

      {scenarios.length > 0 && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard
              label="Best for emissions"
              value={compare.data.best_for_emissions ?? '—'}
              icon={Leaf}
              accent="eco"
            />
            <StatCard
              label="Best value for money"
              value={compare.data.best_value_for_money ?? '—'}
              icon={Coins}
              accent="amber"
            />
            <StatCard
              label="Baseline CO₂e"
              value={base ? compact(base.total_emissions_co2) : '—'}
              unit="t/yr"
              icon={Factory}
              accent="slate"
            />
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Annual CO₂e and operating cost">
              <ChartFrame height={300}>
                <ComposedChart data={chartData} margin={{ top: 10, right: 10, bottom: 10, left: 0 }}>
                  <ThemedGrid />
                  <ThemedXAxis dataKey="name" />
                  <ThemedYAxis yAxisId="left" unit=" t" />
                  <ThemedYAxis
                    yAxisId="right"
                    orientation="right"
                    tickFormatter={(v) => usd(v, { compact: true })}
                    width={72}
                  />
                  <ThemedTooltip
                    formatter={(value, name) =>
                      name === 'Operating cost' ? usd(value) : `${num(value)} t`
                    }
                  />
                  <ThemedLegend />
                  <Bar yAxisId="left" dataKey="co2" name="CO₂e" radius={[4, 4, 0, 0]}>
                    {chartData.map((row) => (
                      <Cell key={row.name} fill={fuelColor(row.name)} />
                    ))}
                  </Bar>
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="cost"
                    name="Operating cost"
                    stroke="#f59e0b"
                    strokeWidth={2.5}
                    dot={{ r: 4 }}
                  />
                </ComposedChart>
              </ChartFrame>
            </Card>

            <Card
              title="Six-way trade-off"
              description="Each axis normalised to 0–100. Nothing wins on every axis — that is the point."
            >
              {radarData.length > 0 && (
                <ChartFrame height={300}>
                  <RadarChart data={radarData} outerRadius="72%">
                    <PolarGrid stroke={theme.grid} />
                    <PolarAngleAxis dataKey="axis" tick={{ fill: theme.axis, fontSize: 11 }} />
                    <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                    <ThemedTooltip formatter={(v) => `${num(v, 0)}/100`} />
                    <ThemedLegend />
                    {alternatives.map((s) => (
                      <Radar
                        key={s.fuel_type}
                        name={s.fuel_type}
                        dataKey={s.fuel_type}
                        stroke={fuelColor(s.fuel_type)}
                        fill={fuelColor(s.fuel_type)}
                        fillOpacity={0.18}
                        strokeWidth={2}
                      />
                    ))}
                  </RadarChart>
                </ChartFrame>
              )}
            </Card>
          </div>

          <Card title="Scenario detail">
            <DataTable
              columns={[
                { key: 'fuel_type', header: 'Fuel' },
                { key: 'scenario_name', header: 'Scenario' },
                {
                  key: 'total_fuel_tons',
                  header: 'Fuel',
                  align: 'right',
                  render: (r) => `${num(r.total_fuel_tons)} t`,
                },
                {
                  key: 'total_emissions_co2',
                  header: 'CO₂e',
                  align: 'right',
                  render: (r) => `${num(r.total_emissions_co2)} t`,
                },
                {
                  key: 'emission_reduction_pct',
                  header: 'CO₂ cut',
                  align: 'right',
                  render: (r) => signedPct(r.emission_reduction_pct),
                },
                {
                  key: 'total_sox_tons',
                  header: 'SOₓ',
                  align: 'right',
                  render: (r) => `${num(r.total_sox_tons, 1)} t`,
                },
                {
                  key: 'total_nox_tons',
                  header: 'NOₓ',
                  align: 'right',
                  render: (r) => `${num(r.total_nox_tons, 1)} t`,
                },
                {
                  key: 'total_cost_usd',
                  header: 'Opex',
                  align: 'right',
                  render: (r) => usd(r.total_cost_usd, { compact: true }),
                },
                {
                  key: 'cost_change_pct',
                  header: 'Δ opex',
                  align: 'right',
                  render: (r) => signedPct(r.cost_change_pct),
                },
                {
                  key: 'retrofit_capex_usd',
                  header: 'Retrofit',
                  align: 'right',
                  render: (r) =>
                    r.retrofit_capex_usd ? usd(r.retrofit_capex_usd, { compact: true }) : '—',
                },
                {
                  key: 'feasibility',
                  header: 'Feasibility',
                  align: 'right',
                  render: (r) => (
                    <Badge
                      tone={r.feasibility > 0.8 ? 'eco' : r.feasibility > 0.5 ? 'warning' : 'danger'}
                    >
                      {pct(r.feasibility * 100, 0)}
                    </Badge>
                  ),
                },
              ]}
              rows={scenarios}
              getRowKey={(row) => row.scenario_name}
              highlightRow={(row) => row.fuel_type === compare.data.best_value_for_money}
            />
            <p className="text-faint mt-3 text-xs">
              Feasibility blends bunker availability with technology readiness. Ammonia scores
              poorly today and that is the honest answer — the scenario is a 2035 question, not a
              2026 one.
            </p>
          </Card>
        </>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Transition                                                                  */
/* -------------------------------------------------------------------------- */
function TransitionTab({ fuels }) {
  const plan = useAsync((signal, body) => api.scenarios.transitionPlan(body, { signal }))
  const [targetFuel, setTargetFuel] = useState('LNG')
  const [targetYear, setTargetYear] = useState(2035)

  const run = useCallback(() => {
    plan.run({ target_fuel: targetFuel, target_year: Number(targetYear) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetFuel, targetYear])

  useEffect(() => {
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const phases = plan.data?.phases ?? []

  return (
    <div className="space-y-5">
      <Card title="Target" description="When the whole fleet should be converted">
        <div className="grid gap-4 sm:grid-cols-3">
          <Select
            label="Target fuel"
            value={targetFuel}
            onChange={(e) => setTargetFuel(e.target.value)}
            options={(fuels ?? [])
              .filter((f) => !['HFO', 'VLSFO'].includes(f.name))
              .map((f) => ({ value: f.name, label: `${f.name} — ${f.display_name}` }))}
            hint={FUEL_NOTES[targetFuel]}
          />
          <NumberInput
            label="Target year"
            min={2028}
            max={2050}
            value={targetYear}
            onChange={(e) => setTargetYear(e.target.value)}
          />
          <div className="flex items-end">
            <Button className="w-full" loading={plan.loading} onClick={run}>
              Build plan
            </Button>
          </div>
        </div>
      </Card>

      {plan.error && <ErrorState error={plan.error} onRetry={run} />}
      {plan.loading && <Skeleton className="h-72 w-full rounded-xl" />}

      {phases.length > 0 && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard
              label="Total capex"
              value={usd(plan.data.total_capex_usd, { compact: true })}
              icon={Coins}
              accent="amber"
            />
            <StatCard
              label="CO₂ reduction by target"
              value={pct(plan.data.final_co2_reduction_pct)}
              icon={TrendingDown}
              accent="eco"
            />
            <StatCard
              label="Phases"
              value={phases.length}
              icon={CalendarRange}
              accent="primary"
              hint={`${phases[0].year} → ${phases[phases.length - 1].year}`}
            />
          </div>

          <Card
            title="Conversion path"
            description="Vessels converted, cumulative capex and the emissions that fall out of it"
          >
            <ChartFrame height={340}>
              <ComposedChart data={phases} margin={{ top: 10, right: 16, bottom: 10, left: 0 }}>
                <defs>
                  <linearGradient id="capexFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.03} />
                  </linearGradient>
                </defs>
                <ThemedGrid />
                <ThemedXAxis dataKey="year" />
                <ThemedYAxis yAxisId="left" unit="%" domain={[0, 100]} />
                <ThemedYAxis
                  yAxisId="right"
                  orientation="right"
                  tickFormatter={(v) => usd(v, { compact: true })}
                  width={72}
                />
                <ThemedTooltip
                  formatter={(value, name) =>
                    name === 'Cumulative capex' ? usd(value) : `${num(value, 1)}%`
                  }
                />
                <ThemedLegend />
                <Area
                  yAxisId="right"
                  type="monotone"
                  dataKey="cumulative_capex_usd"
                  name="Cumulative capex"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  fill="url(#capexFill)"
                />
                <Bar
                  yAxisId="left"
                  dataKey="target_pct_green_fuel"
                  name="Fleet converted"
                  fill="#06a3ee"
                  radius={[4, 4, 0, 0]}
                  barSize={22}
                />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="co2_reduction_pct"
                  name="CO₂ reduction"
                  stroke="#15af73"
                  strokeWidth={2.5}
                  dot={{ r: 3 }}
                />
              </ComposedChart>
            </ChartFrame>
          </Card>

          <Card title="Phase detail">
            <DataTable
              columns={[
                { key: 'year', header: 'Year' },
                { key: 'milestone', header: 'Milestone' },
                { key: 'vessels_converted', header: 'Converted', align: 'right' },
                {
                  key: 'target_pct_green_fuel',
                  header: 'Fleet %',
                  align: 'right',
                  render: (r) => pct(r.target_pct_green_fuel),
                },
                {
                  key: 'cumulative_capex_usd',
                  header: 'Capex to date',
                  align: 'right',
                  render: (r) => usd(r.cumulative_capex_usd, { compact: true }),
                },
                {
                  key: 'annual_co2_tons',
                  header: 'Annual CO₂e',
                  align: 'right',
                  render: (r) => `${num(r.annual_co2_tons)} t`,
                },
                {
                  key: 'co2_reduction_pct',
                  header: 'Cut',
                  align: 'right',
                  render: (r) => pct(r.co2_reduction_pct),
                },
                {
                  key: 'annual_fuel_cost_usd',
                  header: 'Annual fuel',
                  align: 'right',
                  render: (r) => usd(r.annual_fuel_cost_usd, { compact: true }),
                },
              ]}
              rows={phases}
              getRowKey={(row) => row.year}
            />
          </Card>
        </>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Shore power                                                                 */
/* -------------------------------------------------------------------------- */
function ShorePowerTab() {
  const shore = useAsync((signal, body) => api.scenarios.shorePower(body, { signal }))
  const [share, setShare] = useState(60)

  const run = useCallback(() => {
    shore.run({ shore_power_pct: Number(share) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [share])

  useEffect(() => {
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const data = shore.data
  const saves = data ? data.net_cost_change_usd <= 0 : false

  return (
    <div className="space-y-5">
      <Card
        title="Cold ironing"
        description="Shutting the auxiliary engines down alongside and drawing from the quay instead"
      >
        <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <RangeInput
            label="Share of port energy taken from shore"
            value={share}
            min={0}
            max={100}
            step={5}
            onChange={(e) => setShare(Number(e.target.value))}
          />
          <Button loading={shore.loading} onClick={run} icon={Battery}>
            Recalculate
          </Button>
        </div>
      </Card>

      {shore.error && <ErrorState error={shore.error} onRetry={run} />}

      {data && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="CO₂e avoided"
              value={num(data.avoided_co2_tons)}
              unit="t/yr"
              icon={Leaf}
              accent="eco"
              hint={`${pct(data.avoided_pct_of_fleet)} of fleet emissions`}
            />
            <StatCard
              label="Bunker not burnt"
              value={num(data.fuel_saved_tons)}
              unit="t/yr"
              icon={Fuel}
              accent="primary"
            />
            <StatCard
              label="Bunker cost saved"
              value={usd(data.bunker_cost_saved_usd, { compact: true })}
              icon={Coins}
              accent="amber"
            />
            <StatCard
              label="Net cost change"
              value={usd(data.net_cost_change_usd, { compact: true })}
              icon={Plug}
              accent={saves ? 'eco' : 'violet'}
              hint={saves ? 'Shore power is cheaper here' : 'Electricity costs more than the bunker saved'}
            />
          </div>

          <Card title="Where the money goes">
            <ChartFrame height={260}>
              <BarChart
                layout="vertical"
                data={[
                  { name: 'Bunker saved', value: data.bunker_cost_saved_usd, fill: '#15af73' },
                  { name: 'Electricity bought', value: -data.electricity_cost_usd, fill: '#f43f5e' },
                  { name: 'Net', value: -data.net_cost_change_usd, fill: '#06a3ee' },
                ]}
                margin={{ top: 10, right: 24, bottom: 10, left: 20 }}
              >
                <ThemedGrid vertical />
                <ThemedXAxis type="number" tickFormatter={(v) => usd(v, { compact: true })} />
                <ThemedYAxis type="category" dataKey="name" width={130} />
                <ThemedTooltip formatter={(v) => usd(v)} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {[0, 1, 2].map((i) => (
                    <Cell
                      key={i}
                      fill={['#15af73', '#f43f5e', '#06a3ee'][i]}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ChartFrame>
            <Alert tone="info" className="mt-4">
              Port emissions in scope: {num(data.port_emissions_co2_tons)} t/yr. Only ports with a
              shore connection count — eight of the sixteen lanes in the registry have one, which
              is why the achievable share is not 100%.
            </Alert>
          </Card>
        </>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Reference                                                                   */
/* -------------------------------------------------------------------------- */
function ReferenceTab({ fuels }) {
  return (
    <Card
      title="Fuel properties"
      description="The physical constants every calculation on this site is built on"
    >
      <DataTable
        columns={[
          {
            key: 'name',
            header: 'Fuel',
            render: (row) => (
              <span className="inline-flex items-center gap-2">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: fuelColor(row.name) }}
                  aria-hidden
                />
                <span>
                  <span className="font-medium">{row.name}</span>
                  <span className="text-faint block text-xs">{row.display_name}</span>
                </span>
              </span>
            ),
          },
          {
            key: 'energy_density_mj_per_kg',
            header: 'Energy',
            align: 'right',
            render: (r) => `${num(r.energy_density_mj_per_kg, 1)} MJ/kg`,
          },
          {
            key: 'emission_factor_gco2_per_mj',
            header: 'Emission factor',
            align: 'right',
            render: (r) => `${num(r.emission_factor_gco2_per_mj, 1)} g/MJ`,
          },
          {
            key: 'co2_tons_per_ton_fuel',
            header: 'CO₂ per t fuel',
            align: 'right',
            render: (r) => num(r.co2_tons_per_ton_fuel, 3),
          },
          {
            key: 'cost_per_ton',
            header: 'Price',
            align: 'right',
            render: (r) => `${usd(r.cost_per_ton)}/t`,
          },
          {
            key: 'sfc_multiplier',
            header: 'SFC ×',
            align: 'right',
            render: (r) => num(r.sfc_multiplier, 2),
          },
          {
            key: 'sox_factor',
            header: 'SOₓ',
            align: 'right',
            render: (r) => num(r.sox_factor, 1),
          },
          {
            key: 'nox_factor',
            header: 'NOₓ',
            align: 'right',
            render: (r) => num(r.nox_factor, 1),
          },
          {
            key: 'availability_score',
            header: 'Availability',
            align: 'right',
            render: (r) => pct(r.availability_score * 100, 0),
          },
          {
            key: 'readiness_score',
            header: 'Readiness',
            align: 'right',
            render: (r) => pct(r.readiness_score * 100, 0),
          },
        ]}
        rows={fuels ?? []}
        getRowKey={(row) => row.name}
      />
      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        {(fuels ?? []).map((fuel) => (
          <div
            key={fuel.name}
            className="rounded-lg border p-3 text-xs"
            style={{ borderColor: 'rgb(var(--border-subtle))' }}
          >
            <p className="flex items-center gap-2 font-semibold">
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: fuelColor(fuel.name) }}
                aria-hidden
              />
              {fuel.name}
            </p>
            <p className="text-faint mt-1">{FUEL_NOTES[fuel.name]}</p>
          </div>
        ))}
      </div>
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */
export default function Scenarios() {
  const fuels = useFetch((signal) => api.scenarios.fuels({ signal }), [])
  const fleet = useFetch((signal) => api.scenarios.fleet({ signal }), [])
  const [tab, setTab] = useState('compare')

  return (
    <>
      <PageHeader
        title="Fuel transition scenarios"
        description="What changing fuel actually costs — in retrofit capex, in operating cost, and in emissions the fleet stops producing."
      />

      {fuels.error && <ErrorState error={fuels.error} onRetry={fuels.refetch} className="mb-5" />}

      <div
        className="mb-5 flex gap-1 overflow-x-auto border-b"
        style={{ borderColor: 'rgb(var(--border-subtle))' }}
        role="tablist"
      >
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={
              tab === id
                ? '-mb-px flex items-center gap-2 whitespace-nowrap border-b-2 border-primary-600 px-4 py-2.5 text-sm font-medium text-primary-700 dark:text-primary-300'
                : 'text-faint -mb-px flex items-center gap-2 whitespace-nowrap border-b-2 border-transparent px-4 py-2.5 text-sm font-medium transition-colors hover:text-[rgb(var(--text-primary))]'
            }
          >
            <Icon size={15} aria-hidden />
            {label}
          </button>
        ))}
      </div>

      {fuels.loading ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : (
        <>
          {tab === 'compare' && <CompareTab fuels={fuels.data} fleet={fleet.data} />}
          {tab === 'transition' && <TransitionTab fuels={fuels.data} />}
          {tab === 'shore' && <ShorePowerTab />}
          {tab === 'reference' && <ReferenceTab fuels={fuels.data} />}
        </>
      )}
    </>
  )
}
