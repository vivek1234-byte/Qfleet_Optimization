/** Regulatory compliance — MARPOL ECA zones and IMO CII ratings. */
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Droplets,
  Gauge,
  Map as MapIcon,
  Scale,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bar, BarChart, Cell, Line, LineChart, ReferenceLine } from 'recharts'

import VoyageMap from '../components/VoyageMap'
import { useMapViewport } from '../components/WorldMap'
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
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  StatCard,
  cx,
} from '../components/ui'
import { MAP_VIEWS } from '../data/geography'
import { useAsync, useFetch } from '../hooks/useApi'
import { useNetwork } from '../hooks/useNetwork'
import api from '../lib/api'
import {
  CII_BANDS,
  MONTHS,
  OPTIMIZER_PRESETS,
  ciiColor,
  ciiTone,
  seasonColor,
} from '../lib/domain'
import { compact, num, pct } from '../lib/format'
import { setActivePlan, useActivePlan } from '../lib/planStore'

const EMPTY = []

const TABS = [
  { id: 'cii', label: 'Carbon intensity', icon: Gauge },
  { id: 'eca', label: 'Emission control areas', icon: MapIcon },
  { id: 'season', label: 'Seasonal weather', icon: Sparkles },
  { id: 'method', label: 'How it is calculated', icon: Scale },
]

const STATIC_LAYERS = {
  trails: false,
  names: false,
  portLabels: true,
  chokepoints: false,
  eca: true,
  graticule: true,
  weather: false,
}

/* -------------------------------------------------------------------------- */
/* Carbon intensity                                                            */
/* -------------------------------------------------------------------------- */
function CiiTab({ reference, year, setYear, result, cii, assignments }) {
  const navigate = useNavigate()

  const distribution = useMemo(
    () =>
      CII_BANDS.map((band) => ({
        band,
        count: cii?.distribution?.[band] ?? 0,
      })),
    [cii],
  )

  // Every rated vessel plotted against its own required line. Normalising to
  // the ratio is what lets ships of different types and sizes share one axis.
  const scatter = useMemo(
    () =>
      assignments
        .filter((a) => a.cii?.rated)
        .map((a) => ({
          name: a.vessel_name,
          ratio: a.cii.ratio,
          rating: a.cii.rating,
          attained: a.cii.attained_cii,
          required: a.cii.required_cii,
          type: a.vessel_type,
        }))
        .sort((a, b) => a.ratio - b.ratio),
    [assignments],
  )

  // The empty state and the "optimise and rate" action live on the page itself;
  // this panel only has anything to show once a plan has been rated.
  if (!result) return null

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="At C or better"
          value={pct(cii?.compliant_pct ?? 0, 0)}
          icon={CheckCircle2}
          accent={(cii?.compliant_pct ?? 0) >= 60 ? 'eco' : 'amber'}
          hint={`${cii?.compliant_count ?? 0} of ${cii?.rated_count ?? 0} vessels`}
        />
        <StatCard
          label="Needing a plan"
          value={cii?.at_risk?.length ?? 0}
          icon={AlertTriangle}
          accent="violet"
          hint="Rated D or E on this deployment"
        />
        <StatCard
          label="Fleet attained CII"
          value={num(cii?.fleet_attained_cii ?? 0, 2)}
          unit="g/dwt-nm"
          icon={Gauge}
          accent="primary"
        />
        <StatCard
          label="Reduction factor"
          value={pct(cii?.reduction_factor_pct ?? 0, 0)}
          icon={Scale}
          accent="slate"
          hint={`Below the 2019 reference line, for ${cii?.year}`}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <Card
          title="Every vessel against its own requirement"
          description="Attained / required CII — under 1.0 is compliant."
        >
          {scatter.length ? (
            <ChartFrame height={Math.max(220, scatter.length * 26)}>
              <BarChart
                layout="vertical"
                data={scatter}
                margin={{ top: 8, right: 24, bottom: 8, left: 8 }}
              >
                <ThemedGrid vertical />
                <ThemedXAxis
                  type="number"
                  domain={[0, (max) => Math.max(1.4, max * 1.05)]}
                  tickFormatter={(v) => `${v.toFixed(1)}×`}
                />
                <ThemedYAxis type="category" dataKey="name" width={150} interval={0} />
                <ThemedTooltip
                  formatter={(v, _n, entry) =>
                    `${v.toFixed(3)}× required (attained ${entry.payload.attained} vs ${entry.payload.required})`
                  }
                />
                <ReferenceLine
                  x={1}
                  stroke="#f59e0b"
                  strokeDasharray="4 3"
                  label={{ value: 'required', fontSize: 11, fill: '#f59e0b', position: 'top' }}
                />
                <Bar dataKey="ratio" radius={[0, 4, 4, 0]} barSize={14}>
                  {scatter.map((row) => (
                    <Cell key={row.name} fill={ciiColor(row.rating)} />
                  ))}
                </Bar>
              </BarChart>
            </ChartFrame>
          ) : (
            <p className="text-faint py-8 text-center text-sm">No rated vessels in this plan.</p>
          )}
        </Card>

        <div className="space-y-5">
          <Card title="Rating distribution">
            <ChartFrame height={180}>
              <BarChart data={distribution} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
                <ThemedGrid />
                <ThemedXAxis dataKey="band" />
                <ThemedYAxis allowDecimals={false} width={36} />
                <ThemedTooltip />
                <Bar dataKey="count" name="Vessels" radius={[4, 4, 0, 0]}>
                  {distribution.map((row) => (
                    <Cell key={row.band} fill={ciiColor(row.band)} />
                  ))}
                </Bar>
              </BarChart>
            </ChartFrame>
            <dl className="mt-2 space-y-1.5 text-xs">
              {CII_BANDS.map((band) => (
                <div key={band} className="flex items-start gap-2">
                  <span
                    className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded text-[0.6rem] font-bold text-white"
                    style={{ backgroundColor: ciiColor(band) }}
                  >
                    {band}
                  </span>
                  <span className="text-faint">
                    {band === 'A' && 'Major superior performance.'}
                    {band === 'B' && 'Minor superior performance.'}
                    {band === 'C' && 'Meets the required carbon intensity.'}
                    {band === 'D' && 'Three consecutive years forces a corrective action plan.'}
                    {band === 'E' && 'A single year forces a corrective action plan.'}
                  </span>
                </div>
              ))}
            </dl>
          </Card>

          <Card title="Compliance year">
            <div className="flex flex-wrap gap-1.5">
              {[2023, 2024, 2025, 2026, 2028, 2030].map((y) => (
                <button
                  key={y}
                  type="button"
                  onClick={() => setYear(y)}
                  className={cx(
                    'rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors',
                    y === year
                      ? 'border-primary-500 bg-primary-50 text-primary-700 dark:bg-primary-950/50 dark:text-primary-200'
                      : 'hover:bg-[rgb(var(--surface-sunken))]',
                  )}
                  style={y === year ? undefined : { borderColor: 'rgb(var(--border-strong))' }}
                >
                  {y}
                </button>
              ))}
            </div>
            <p className="text-faint mt-2 text-xs">
              The required line tightens every year: {pct(reference?.reduction_factor_pct ?? 0, 0)}{' '}
              below the 2019 reference for {year}.{' '}
              {year > 2026 &&
                'Factors past 2026 are an extrapolation of the agreed trend, not adopted regulation.'}
            </p>
          </Card>
        </div>
      </div>

      {cii?.at_risk?.length > 0 && (
        <Alert tone="warning" title={`${cii.at_risk.length} vessels rated D or E on this plan`}>
          <p className="mt-1">
            {cii.at_risk.map((v) => v.vessel_name).join(', ')}. Try adjusting speed or fuel in the
            sandbox to improve ratings.
          </p>
          <Button size="sm" variant="secondary" className="mt-3" onClick={() => navigate('/sandbox')}>
            Open the sandbox
          </Button>
        </Alert>
      )}
    </div>
  )
}

/** The full rated-vessel table, revealed by "View all vessels". */
function RatedVessels({ assignments, cii }) {
  return (
    <>
      <DataTable
        columns={[
          { key: 'vessel_name', header: 'Vessel' },
          { key: 'vessel_type', header: 'Class' },
          { key: 'route_name', header: 'Lane' },
          {
            key: 'attained',
            header: 'Attained',
            align: 'right',
            render: (row) => (row.cii?.rated ? num(row.cii.attained_cii, 2) : '—'),
          },
          {
            key: 'required',
            header: 'Required',
            align: 'right',
            render: (row) => (row.cii?.rated ? num(row.cii.required_cii, 2) : '—'),
          },
          {
            key: 'ratio',
            header: 'Ratio',
            align: 'right',
            render: (row) => (row.cii?.rated ? `${num(row.cii.ratio, 3)}×` : '—'),
          },
          {
            key: 'rating',
            header: 'Rating',
            render: (row) =>
              row.cii?.rated ? <Badge tone={ciiTone(row.cii.rating)}>{row.cii.rating}</Badge> : '—',
          },
          {
            key: 'speed_knots',
            header: 'Speed',
            align: 'right',
            render: (row) => `${num(row.speed_knots, 1)} kn`,
          },
          { key: 'fuel_type', header: 'Fuel' },
        ]}
        rows={assignments}
        getRowKey={(row) => `${row.vessel_id}-${row.route_id}`}
        highlightRow={(row) => row.cii?.rating === 'D' || row.cii?.rating === 'E'}
      />
      {cii?.caveats?.length > 0 && (
        <ul className="text-faint mt-4 list-inside list-disc space-y-1 text-xs">
          {cii.caveats.map((caveat) => (
            <li key={caveat}>{caveat}</li>
          ))}
        </ul>
      )}
    </>
  )
}

/* -------------------------------------------------------------------------- */
/* Emission control areas                                                      */
/* -------------------------------------------------------------------------- */
function EcaTab({ network, eca }) {
  const viewport = useMapViewport(MAP_VIEWS.europe.box)
  const affected = (eca?.lanes ?? EMPTY).filter((l) => l.eca_fraction > 0)

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label="Zones in force"
          value={eca?.zones?.length ?? 0}
          icon={MapIcon}
          accent="amber"
        />
        <StatCard
          label="Lanes affected"
          value={eca?.affected_lane_count ?? 0}
          icon={AlertTriangle}
          accent="violet"
          hint={`of ${network.lanes.length} in the registry`}
        />
        <StatCard
          label="Sulphur cap inside"
          value={`${eca?.eca_sulphur_limit_pct ?? 0.1}%`}
          icon={Droplets}
          accent="primary"
          hint={`Against ${eca?.global_sulphur_cap_pct ?? 0.5}% globally since IMO 2020`}
        />
      </div>

      <Card title="Where the zones are" bodyClassName="p-0">
        <div className="h-[46vh] min-h-[320px] overflow-hidden rounded-b-xl">
          {network.loading ? (
            <Skeleton className="h-full w-full" />
          ) : (
            <VoyageMap
              viewport={viewport}
              network={network}
              ships={EMPTY}
              clockRef={{ current: { hours: 0 } }}
              running={false}
              timeScale={0}
              layers={STATIC_LAYERS}
            />
          )}
        </div>
      </Card>

      <Card
        title="Exposure by lane"
        description="How much of each voyage runs inside a controlled area"
      >
        {affected.length ? (
          <DataTable
            columns={[
              { key: 'name', header: 'Lane' },
              {
                key: 'eca_fraction',
                header: 'Share of voyage',
                align: 'right',
                render: (row) => (
                  <span className="inline-flex items-center justify-end gap-2">
                    <span className="h-1.5 w-16 overflow-hidden rounded-full bg-[rgb(var(--surface-sunken))]">
                      <span
                        className="block h-full rounded-full bg-amber-500"
                        style={{ width: `${row.eca_fraction * 100}%` }}
                      />
                    </span>
                    {pct(row.eca_fraction * 100, 1)}
                  </span>
                ),
              },
              {
                key: 'eca_nm',
                header: 'Distance inside',
                align: 'right',
                render: (row) => `${num(row.eca_nm)} nm`,
              },
              {
                key: 'zones',
                header: 'Zones',
                render: (row) =>
                  row.zones.map((z) => `${z.zone} (${num(z.nm)} nm)`).join(', ') || '—',
              },
            ]}
            rows={affected}
            getRowKey={(row) => row.name}
          />
        ) : (
          <p className="text-faint py-8 text-center text-sm">
            No lane in the registry enters a controlled area.
          </p>
        )}

        <Alert tone="info" className="mt-4" title="Optimiser impact">
          Ships on HFO/VLSFO pay a distillate-switch cost proportional to ECA exposure. Vessels
          already on LNG, methanol, or ammonia avoid this penalty automatically.
        </Alert>
      </Card>

      <Card title="Zones">
        <DataTable
          columns={[
            { key: 'name', header: 'Area' },
            {
              key: 'pollutants',
              header: 'Controls',
              render: (row) => row.pollutants.join(', '),
            },
            {
              key: 'sulphur_limit_pct',
              header: 'Sulphur cap',
              align: 'right',
              render: (row) => `${row.sulphur_limit_pct}%`,
            },
            { key: 'in_force_since', header: 'In force' },
            { key: 'note', header: 'Note', render: (row) => row.note || '—' },
          ]}
          rows={eca?.zones ?? EMPTY}
          getRowKey={(row) => row.short_name}
        />
        {eca?.disclaimer && <p className="text-faint mt-3 text-xs">{eca.disclaimer}</p>}
      </Card>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Seasonal weather                                                            */
/* -------------------------------------------------------------------------- */
function SeasonTab({ seasonality }) {
  const [laneName, setLaneName] = useState(null)
  const lanes = seasonality?.lanes ?? EMPTY
  const basins = seasonality?.basins ?? EMPTY
  const lane = lanes.find((l) => l.name === laneName) ?? lanes[0]

  const laneCurve = useMemo(
    () =>
      (lane?.monthly ?? EMPTY).map((m) => ({
        month: MONTHS[m.month - 1].short,
        factor: m.factor,
        beaufort: (lane?.annual_mean_beaufort ?? 0) * m.factor,
        season: m.season,
      })),
    [lane],
  )

  const basinRows = useMemo(
    () =>
      Array.from({ length: 12 }, (_, i) => {
        const row = { month: MONTHS[i].short }
        basins.forEach((b) => {
          row[b.name] = b.monthly_factor[i]
        })
        return row
      }),
    [basins],
  )

  const BASIN_COLORS = [
    '#06a3ee',
    '#15af73',
    '#f59e0b',
    '#a78bfa',
    '#ef4444',
    '#14b8a6',
    '#ec4899',
    '#84cc16',
  ]

  return (
    <div className="space-y-5">
      <Card
        title="The monsoon, lane by lane"
        description="Pick a lane to see how its sea state moves through the year"
        actions={
          <select
            className="field-control w-56"
            value={lane?.name ?? ''}
            onChange={(e) => setLaneName(e.target.value)}
            aria-label="Lane"
          >
            {lanes.map((l) => (
              <option key={l.name} value={l.name}>
                {l.name}
              </option>
            ))}
          </select>
        }
      >
        {laneCurve.length ? (
          <>
            <ChartFrame height={260}>
              <BarChart data={laneCurve} margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
                <ThemedGrid />
                <ThemedXAxis dataKey="month" />
                <ThemedYAxis
                  domain={[0, 'dataMax + 1']}
                  tickFormatter={(v) => v.toFixed(1)}
                  width={48}
                  label={{
                    value: 'Beaufort',
                    angle: -90,
                    position: 'insideLeft',
                    offset: 8,
                    fontSize: 12,
                  }}
                />
                <ThemedTooltip
                  formatter={(v, _n, entry) => [
                    `${v.toFixed(2)} Bft · ×${entry.payload.factor.toFixed(2)}`,
                    entry.payload.season,
                  ]}
                />
                <ReferenceLine
                  y={lane?.annual_mean_beaufort}
                  stroke="#94a3b8"
                  strokeDasharray="4 3"
                  label={{ value: 'annual mean', fontSize: 11, fill: '#94a3b8', position: 'right' }}
                />
                <Bar dataKey="beaufort" name="Sea state" radius={[4, 4, 0, 0]}>
                  {laneCurve.map((row) => (
                    <Cell key={row.month} fill={seasonColor(row.factor)} />
                  ))}
                </Bar>
              </BarChart>
            </ChartFrame>
            <p className="text-faint mt-2 text-xs">
              {lane?.name} is{' '}
              {lane?.basins
                ?.map((b) => `${pct(b.share * 100, 0)} ${b.basin}`)
                .join(', ')}
              . Weather penalty:{' '}
              <span className="numeric">1 + 0.02 B^1.5</span>.
            </p>
          </>
        ) : (
          <Skeleton className="h-56 w-full" />
        )}
      </Card>

      <Card
        title="Every basin, every month"
        description="Multiplier on the annual-mean sea state"
      >
        <ChartFrame height={300}>
          <LineChart data={basinRows} margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
            <ThemedGrid />
            <ThemedXAxis dataKey="month" />
            <ThemedYAxis domain={[0.7, 1.5]} tickFormatter={(v) => `×${v.toFixed(1)}`} width={54} />
            <ThemedTooltip formatter={(v) => `×${v.toFixed(2)}`} />
            <ReferenceLine y={1} stroke="#94a3b8" strokeDasharray="3 3" />
            {basins.map((basin, i) => (
              <Line
                key={basin.name}
                type="monotone"
                dataKey={basin.name}
                stroke={BASIN_COLORS[i % BASIN_COLORS.length]}
                strokeWidth={2}
                dot={false}
              />
            ))}
          </LineChart>
        </ChartFrame>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
          {basins.map((basin, i) => (
            <span key={basin.name} className="flex items-center gap-1.5 text-xs">
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: BASIN_COLORS[i % BASIN_COLORS.length] }}
                aria-hidden
              />
              {basin.name}
              <span className="text-faint">roughest {basin.roughest_month.slice(0, 3)}</span>
            </span>
          ))}
        </div>
        {seasonality?.note && <p className="text-faint mt-3 text-xs">{seasonality.note}</p>}
      </Card>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Method                                                                      */
/* -------------------------------------------------------------------------- */
function MethodTab({ reference }) {
  if (!reference) return <Skeleton className="h-80 w-full rounded-xl" />

  return (
    <div className="space-y-5">
      <Card
        title="The carbon intensity calculation"
        description="Published so it can be checked rather than trusted"
      >
        <dl className="space-y-2.5 text-sm">
          {Object.entries(reference.formulae ?? {}).map(([key, formula]) => (
            <div key={key} className="flex flex-col gap-0.5 sm:flex-row sm:gap-4">
              <dt className="text-faint w-28 shrink-0 capitalize">{key}</dt>
              <dd className="numeric rounded bg-[rgb(var(--surface-sunken))] px-2 py-1 text-xs">
                {formula}
              </dd>
            </div>
          ))}
        </dl>

        <div className="mt-5">
          <p className="text-faint mb-2 text-xs font-semibold uppercase tracking-wide">
            Reference-line constants
          </p>
          <DataTable
            columns={[
              { key: 'label', header: 'Ship type' },
              { key: 'a', header: 'a', align: 'right' },
              { key: 'c', header: 'c', align: 'right' },
              { key: 'capacity_basis', header: 'Capacity' },
              {
                key: 'dd_vector',
                header: 'Band boundaries (d₁–d₄)',
                align: 'right',
                render: (row) => row.dd_vector.map((d) => d.toFixed(2)).join(' · '),
              },
              {
                key: 'capacity_cap',
                header: 'Capped at',
                align: 'right',
                render: (row) => (row.capacity_cap ? `${compact(row.capacity_cap)} dwt` : '—'),
              },
            ]}
            rows={reference.ship_types ?? EMPTY}
            getRowKey={(row) => row.vessel_type}
          />
        </div>

        <div className="mt-5">
          <p className="text-faint mb-2 text-xs font-semibold uppercase tracking-wide">
            Reduction factor Z, below the 2019 reference line
          </p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(reference.adopted_reduction_factors ?? {}).map(([year, z]) => (
              <span
                key={year}
                className="rounded-lg border px-2.5 py-1 text-xs"
                style={{ borderColor: 'rgb(var(--border-subtle))' }}
              >
                <span className="font-medium">{year}</span>{' '}
                <span className="numeric text-faint">{z}%</span>
              </span>
            ))}
            <span className="text-faint self-center text-xs">
              then +{reference.assumed_trend_pct_per_year}% a year, extrapolated
            </span>
          </div>
        </div>

        <ul className="text-faint mt-5 list-inside list-disc space-y-1 text-xs">
          {(reference.sources ?? EMPTY).map((source) => (
            <li key={source}>{source}</li>
          ))}
        </ul>
      </Card>

      <Card
        title="Required line, vessel by vessel"
        description={`What each ship in the registry has to get under in ${reference.year}`}
      >
        <DataTable
          columns={[
            { key: 'name', header: 'Vessel' },
            { key: 'vessel_type', header: 'Class' },
            {
              key: 'dwt',
              header: 'Deadweight',
              align: 'right',
              render: (row) => `${compact(row.dwt)} t`,
            },
            {
              key: 'reference_cii',
              header: '2019 reference',
              align: 'right',
              render: (row) => num(row.reference_cii, 3),
            },
            {
              key: 'required_cii',
              header: `Required ${reference.year}`,
              align: 'right',
              render: (row) => num(row.required_cii, 3),
            },
            ...['A_B', 'B_C', 'C_D', 'D_E'].map((key) => ({
              key,
              header: key.replace('_', '/'),
              align: 'right',
              render: (row) => num(row.boundaries[key], 2),
            })),
          ]}
          rows={reference.vessels ?? EMPTY}
          getRowKey={(row) => row.name}
        />
        <p className="text-faint mt-3 text-xs">All figures in {reference.unit}.</p>
      </Card>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */
export default function Compliance() {
  const [tab, setTab] = useState('cii')
  const [year, setYear] = useState(2026)
  const [showAll, setShowAll] = useState(false)

  const network = useNetwork()
  const eca = useFetch((signal) => api.regulatory.ecaZones({ signal }), [])
  const seasonality = useFetch((signal) => api.regulatory.seasonality({ signal }), [])
  const reference = useFetch(
    (signal) => api.regulatory.ciiReference({ year }, { signal }),
    [year],
  )

  // Rating state lives here now: the headline counts and the at-risk list are
  // the page, and the tabs below read the same result.
  const active = useActivePlan()
  const optimise = useAsync((signal, body) => api.optimization.optimize(body, { signal }))
  const result = optimise.data ?? active.result
  const cii = result?.plan?.compliance?.cii
  const assignments = result?.plan?.assignments ?? EMPTY
  // Worst ratio first, so the ship that needs the most attention reads first.
  const atRisk = useMemo(
    () => (cii?.at_risk ?? EMPTY).slice().sort((a, b) => b.ratio - a.ratio),
    [cii],
  )

  const runDemo = async () => {
    const res = await optimise.run({
      ...OPTIMIZER_PRESETS[1].config,
      algorithm: 'qpso',
      seed: 42,
      include_plan: true,
    })
    if (res) setActivePlan(res, 'compliance')
  }

  const error = network.error || eca.error || seasonality.error || reference.error

  return (
    <>
      <PageHeader title="Compliance" description="Which vessels need attention." />

      {error && <ErrorState error={error} onRetry={network.refetch} className="mb-5" />}
      {optimise.error && <ErrorState error={optimise.error} onRetry={runDemo} className="mb-5" />}

      {!result ? (
        <Card className="mb-6">
          <EmptyState
            icon={ShieldCheck}
            title="Rate a deployment plan"
            description="Run a deployment plan to see CII ratings for every vessel."
            action={
              <Button icon={Sparkles} loading={optimise.loading} onClick={runDemo}>
                Optimise and rate
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="mb-8">
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
            <span className="inline-flex items-center gap-2 text-eco-600 dark:text-eco-400">
              <CheckCircle2 size={16} aria-hidden />
              <span className="numeric font-semibold">{cii?.compliant_count ?? 0}</span> vessels
              compliant
            </span>
            <span className="inline-flex items-center gap-2 text-amber-600 dark:text-amber-400">
              <AlertTriangle size={16} aria-hidden />
              <span className="numeric font-semibold">{atRisk.length}</span> need attention
            </span>
          </div>

          {atRisk.length > 0 && (
            <ul className="mt-5">
              {atRisk.map((vessel) => (
                <li
                  key={vessel.vessel_name}
                  className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 border-b py-3 last:border-b-0"
                  style={{ borderColor: 'rgb(var(--border-subtle))' }}
                >
                  <span className="truncate font-medium">{vessel.vessel_name}</span>
                  <span className="flex items-center gap-6">
                    <Badge tone={vessel.rating === 'E' ? 'danger' : 'warning'}>
                      CII {vessel.rating}
                    </Badge>
                    <span
                      className={cx(
                        'text-sm font-medium',
                        vessel.rating === 'E'
                          ? 'text-rose-600 dark:text-rose-400'
                          : 'text-amber-600 dark:text-amber-400',
                      )}
                    >
                      {vessel.rating === 'E' ? 'Action required' : 'Monitor'}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}

          <button
            type="button"
            onClick={() => setShowAll((open) => !open)}
            aria-expanded={showAll}
            className="mt-4 text-sm font-medium text-primary-600 transition-colors hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300"
          >
            {showAll ? 'Hide all vessels' : 'View all vessels'}
          </button>

          {showAll && (
            <div className="mt-4">
              <RatedVessels assignments={assignments} cii={cii} />
            </div>
          )}
        </div>
      )}

      <details className="group">
        <summary className="expand-toggle cursor-pointer list-none [&::-webkit-details-marker]:hidden">
          Technical details
          <ChevronDown
            size={14}
            className="text-faint transition-transform group-open:rotate-180"
            aria-hidden
          />
        </summary>
        <div className="pt-4">
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

          {tab === 'cii' && (
            <CiiTab
              reference={reference.data}
              year={year}
              setYear={setYear}
              result={result}
              cii={cii}
              assignments={assignments}
            />
          )}
          {tab === 'eca' && <EcaTab network={network} eca={eca.data} />}
          {tab === 'season' && <SeasonTab seasonality={seasonality.data} />}
          {tab === 'method' && <MethodTab reference={reference.data} />}
        </div>
      </details>
    </>
  )
}
