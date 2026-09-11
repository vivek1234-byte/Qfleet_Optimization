/**
 * Live voyage simulator.
 *
 * The map is the product. Everything else in the app produces numbers; this is
 * where an operator can see what the numbers mean — which ship is where, how
 * fast it is going, what it is burning.
 *
 * Split mode is the argument in one screen: the same fleet sailing
 * unoptimised on the left and the solver's plan on the right, on one clock,
 * with the gap between them counting up live. Both panes share a viewport, so
 * panning one pans the other and the comparison stays honest.
 */
import {
  Anchor,
  Columns2,
  Crosshair,
  Droplets,
  Gauge,
  Layers,
  Leaf,
  Maximize2,
  Pause,
  Play,
  RotateCcw,
  Ship as ShipIcon,
  Sparkles,
  TrendingDown,
  Wind,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import VoyageMap from '../components/VoyageMap'
import { useMapViewport } from '../components/WorldMap'
import { Alert, Badge, Button, Checkbox, ErrorState, Select, cx } from '../components/ui'
import { MAP_VIEWS } from '../data/geography'
import { useAsync, useFetch } from '../hooks/useApi'
import { useNetwork } from '../hooks/useNetwork'
import api from '../lib/api'
import { MONTHS, OPTIMIZER_PRESETS, beaufortLabel, ciiColor, fuelColor } from '../lib/domain'
import { compact, num, pct, usd } from '../lib/format'
import { setActivePlan, useActivePlan } from '../lib/planStore'
import {
  TIME_SCALES,
  formatDuration,
  formatSimClock,
  shipsFromPlan,
  shipsFromRegistry,
} from '../lib/simulation'

const EMPTY = []

/* -------------------------------------------------------------------------- */
/* Small pieces                                                                */
/* -------------------------------------------------------------------------- */
function Ticker({ label, value, unit, icon: Icon, tone = 'text-primary-400', delta }) {
  return (
    <div className="flex items-center gap-2.5">
      <Icon size={16} className={cx('shrink-0', tone)} aria-hidden />
      <div className="min-w-0">
        <p className="text-faint text-[0.68rem] font-medium uppercase tracking-wide">{label}</p>
        <p className="ticker-value truncate text-sm font-semibold">
          {value}
          {unit && <span className="text-faint ml-1 text-xs font-normal">{unit}</span>}
          {delta && <span className="ml-1.5 text-xs font-medium text-eco-500">{delta}</span>}
        </p>
      </div>
    </div>
  )
}

function VesselRow({ snapshot, selected, onSelect }) {
  const color = fuelColor(snapshot.fuelType)
  const rating = snapshot.cii
  return (
    <button
      type="button"
      onClick={() => onSelect(selected ? null : snapshot.id)}
      className={cx(
        'w-full rounded-lg border p-2.5 text-left transition-colors',
        selected
          ? 'border-primary-500 bg-primary-50 dark:bg-primary-950/40'
          : 'hover:bg-[rgb(var(--surface-sunken))]',
      )}
      style={selected ? undefined : { borderColor: 'rgb(var(--border-subtle))' }}
    >
      <div className="flex items-center gap-2">
        <span
          className="h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ backgroundColor: color }}
          aria-hidden
        />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{snapshot.vesselName}</span>
        {rating && (
          <span
            className="grid h-4 w-4 shrink-0 place-items-center rounded text-[0.6rem] font-bold text-white"
            style={{ backgroundColor: ciiColor(rating) }}
            title={`IMO carbon intensity rating ${rating}`}
          >
            {rating}
          </span>
        )}
        <span className="numeric text-faint shrink-0 text-xs">
          {snapshot.berthed ? 'in port' : `${snapshot.speedKnots.toFixed(1)} kn`}
        </span>
      </div>
      <p className="text-faint mt-0.5 truncate text-xs">
        {snapshot.berthed ? (
          <>Alongside {snapshot.port}</>
        ) : (
          <>
            {snapshot.laneName} {snapshot.inbound ? '(return)' : ''} · ETA{' '}
            {formatDuration(snapshot.etaHours)}
          </>
        )}
      </p>
      <div className="mt-1.5 flex items-center gap-2">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-[rgb(var(--surface-sunken))]">
          <div
            className="h-full rounded-full transition-[width] duration-200"
            style={{ width: `${Math.min(snapshot.progressPct, 100)}%`, backgroundColor: color }}
          />
        </div>
        <span className="numeric text-faint w-20 shrink-0 text-right text-[0.68rem]">
          {num(snapshot.fuelTons, 0)} t · {num(snapshot.co2Tons, 0)} t
        </span>
      </div>
      {selected && (
        <dl
          className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1 border-t pt-2 text-xs"
          style={{ borderColor: 'rgb(var(--border-subtle))' }}
        >
          <dt className="text-faint">Class</dt>
          <dd className="text-right">{snapshot.vesselType}</dd>
          <dt className="text-faint">Fuel</dt>
          <dd className="text-right">{snapshot.fuelType}</dd>
          <dt className="text-faint">Shore power</dt>
          <dd className="numeric text-right">{pct(snapshot.shorePowerPct, 0)}</dd>
          <dt className="text-faint">Sailed</dt>
          <dd className="numeric text-right">{num(snapshot.sailedNm)} nm</dd>
          <dt className="text-faint">Remaining</dt>
          <dd className="numeric text-right">{num(snapshot.remainingNm)} nm</dd>
          <dt className="text-faint">Leg cost</dt>
          <dd className="numeric text-right">{usd(snapshot.costUsd, { compact: true })}</dd>
          {snapshot.ecaFraction > 0 && (
            <>
              <dt className="text-faint">In an ECA</dt>
              <dd className="numeric text-right text-amber-600 dark:text-amber-400">
                {pct(snapshot.ecaFraction * 100, 0)} of the lane
              </dd>
            </>
          )}
        </dl>
      )}
    </button>
  )
}

function LayerToggles({ layers, setLayers }) {
  const items = [
    ['trails', 'Wake trails'],
    ['names', 'Vessel names'],
    ['portLabels', 'Port labels'],
    ['chokepoints', 'Chokepoints'],
    ['eca', 'Emission control areas'],
    ['graticule', 'Graticule'],
    ['weather', 'Colour lanes by sea state'],
  ]
  return (
    <div className="space-y-2">
      {items.map(([key, label]) => (
        <Checkbox
          key={key}
          label={label}
          checked={layers[key]}
          onChange={(e) => setLayers((l) => ({ ...l, [key]: e.target.checked }))}
        />
      ))}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */
export default function Simulator() {
  const network = useNetwork()
  const fuels = useFetch((signal) => api.scenarios.fuels({ signal }), [])
  const active = useActivePlan()
  const optimise = useAsync((signal, body) => api.optimization.optimize(body, { signal }))

  const [running, setRunning] = useState(true)
  const [scaleId, setScaleId] = useState('faster')
  const [split, setSplit] = useState(false)
  const [selectedId, setSelectedId] = useState(null)
  const [fuelFilter, setFuelFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [month, setMonth] = useState('')
  const [snapshots, setSnapshots] = useState(EMPTY)
  const [baselineSnapshots, setBaselineSnapshots] = useState(EMPTY)
  const [clockHours, setClockHours] = useState(0)
  const [layers, setLayers] = useState({
    trails: true,
    names: false,
    portLabels: true,
    chokepoints: true,
    eca: false,
    graticule: true,
    weather: false,
  })

  // One clock for both panes. Sharing the ref is what keeps a split view
  // honest: the two fleets are always at the same moment.
  const clockRef = useRef({ hours: 0 })
  const viewport = useMapViewport(MAP_VIEWS.indianOcean.box)
  const { setBox, zoomBy } = viewport

  const fuelsByName = useMemo(
    () => Object.fromEntries((fuels.data ?? EMPTY).map((f) => [f.name, f])),
    [fuels.data],
  )

  /* ---- fleets ----------------------------------------------------------- */
  const planResult = active.result
  const baselineShips = useMemo(
    () =>
      network.registry && fuels.data
        ? shipsFromRegistry(network.registry, fuelsByName, { limit: 14 })
        : EMPTY,
    [network.registry, fuels.data, fuelsByName],
  )
  const planShips = useMemo(
    () => (planResult ? shipsFromPlan(planResult, network.lanesByName) : EMPTY),
    [planResult, network.lanesByName],
  )
  const ships = planShips.length ? planShips : baselineShips
  const usingPlan = planShips.length > 0

  /* ---- filtering -------------------------------------------------------- */
  const matches = useCallback(
    (ship) =>
      (fuelFilter === 'all' || ship.fuelType === fuelFilter) &&
      (typeFilter === 'all' || ship.vesselType === typeFilter),
    [fuelFilter, typeFilter],
  )
  const dimmedIds = useMemo(
    () => new Set(ships.filter((s) => !matches(s)).map((s) => s.id)),
    [ships, matches],
  )
  const visibleShips = useMemo(() => ships.filter(matches), [ships, matches])
  const activeLanes = useMemo(
    () => new Set(visibleShips.map((s) => s.laneName)),
    [visibleShips],
  )
  const activePorts = useMemo(() => {
    const set = new Set()
    visibleShips.forEach((ship) => {
      const lane = network.lanesByName[ship.laneName]
      if (lane) {
        set.add(lane.origin)
        set.add(lane.destination)
      }
    })
    return set
  }, [visibleShips, network.lanesByName])

  /* ---- clock ------------------------------------------------------------ */
  const timeScale = TIME_SCALES.find((s) => s.id === scaleId) ?? TIME_SCALES[2]

  const onTick = useCallback((hours, next) => {
    setClockHours(hours)
    setSnapshots(next)
  }, [])
  const onBaselineTick = useCallback((_hours, next) => setBaselineSnapshots(next), [])

  const resetClock = useCallback(() => {
    clockRef.current.hours = 0
    setClockHours(0)
  }, [])

  useEffect(() => {
    const onKey = (event) => {
      if (event.code !== 'Space') return
      const tag = event.target?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || tag === 'BUTTON') return
      event.preventDefault()
      setRunning((r) => !r)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  /* ---- totals ----------------------------------------------------------- */
  const visibleIds = useMemo(() => new Set(visibleShips.map((s) => s.id)), [visibleShips])

  const summarise = useCallback((rows) => {
    const atSea = rows.filter((s) => !s.berthed)
    return {
      vessels: rows.length,
      atSea: atSea.length,
      inPort: rows.length - atSea.length,
      fuel: rows.reduce((a, s) => a + s.fuelTons, 0),
      co2: rows.reduce((a, s) => a + s.co2Tons, 0),
      cost: rows.reduce((a, s) => a + s.costUsd, 0),
      avgSpeed: atSea.length ? atSea.reduce((a, s) => a + s.speedKnots, 0) / atSea.length : 0,
    }
  }, [])

  const totals = useMemo(
    () => summarise(snapshots.filter((s) => visibleIds.has(s.id))),
    [snapshots, visibleIds, summarise],
  )
  const baselineTotals = useMemo(
    () => summarise(baselineSnapshots),
    [baselineSnapshots, summarise],
  )

  // In split mode the two fleets may be different sizes, so compare per-vessel
  // rates rather than raw sums or the optimised side looks better than it is
  // purely for having fewer ships.
  const divergence = useMemo(() => {
    if (!split || !baselineTotals.vessels || !totals.vessels) return null
    const perShip = (t, key) => t[key] / Math.max(t.vessels, 1)
    const gap = (key) => {
      const base = perShip(baselineTotals, key)
      const opt = perShip(totals, key)
      return base > 0 ? ((base - opt) / base) * 100 : 0
    }
    return {
      fuel: gap('fuel'),
      co2: gap('co2'),
      cost: gap('cost'),
      absFuel: perShip(baselineTotals, 'fuel') - perShip(totals, 'fuel'),
      absCo2: perShip(baselineTotals, 'co2') - perShip(totals, 'co2'),
    }
  }, [split, totals, baselineTotals])

  const snapshotById = useMemo(
    () => Object.fromEntries(snapshots.map((s) => [s.id, s])),
    [snapshots],
  )

  /* ---- actions ---------------------------------------------------------- */
  const runOptimiser = useCallback(async () => {
    const result = await optimise.run({
      ...OPTIMIZER_PRESETS[0].config,
      algorithm: 'qpso',
      seed: 42,
      include_plan: true,
      month: month === '' ? null : Number(month),
    })
    if (result) {
      setActivePlan(result, 'simulator')
      resetClock()
      setSplit(true)
    }
  }, [optimise, resetClock, month])

  const centreOnSelected = useCallback(() => {
    const snapshot = snapshotById[selectedId]
    const lane = snapshot && network.lanesByName[snapshot.laneName]
    const geometry = lane && network.geometries[lane.name]
    if (!geometry) return
    const xs = geometry.xy.map((p) => p[0])
    const ys = geometry.xy.map((p) => p[1])
    const pad = 8
    setBox([
      Math.min(...xs) - pad,
      Math.min(...ys) - pad,
      Math.max(Math.max(...xs) - Math.min(...xs) + pad * 2, 20),
      Math.max(Math.max(...ys) - Math.min(...ys) + pad * 2, 16),
    ])
  }, [snapshotById, selectedId, network, setBox])

  const fuelOptions = useMemo(() => {
    const present = [...new Set(ships.map((s) => s.fuelType))]
    return [{ value: 'all', label: 'All fuels' }, ...present.map((f) => ({ value: f, label: f }))]
  }, [ships])
  const typeOptions = useMemo(() => {
    const present = [...new Set(ships.map((s) => s.vesselType))]
    return [{ value: 'all', label: 'All classes' }, ...present.map((t) => ({ value: t, label: t }))]
  }, [ships])
  const legendFuels = useMemo(() => [...new Set(ships.map((s) => s.fuelType))], [ships])

  const ciiSummary = planResult?.plan?.compliance?.cii
  const loading = network.loading || fuels.loading
  const error = network.error || fuels.error

  /* ---- render ----------------------------------------------------------- */
  const mapHeight = split
    ? 'h-[42vh] min-h-[300px] xl:h-[calc(100vh-21rem)]'
    : 'h-[58vh] min-h-[380px] xl:h-[calc(100vh-21rem)]'

  return (
    <div className="space-y-3">
      {error && <ErrorState error={error} onRetry={network.refetch} />}
      {optimise.error && <ErrorState error={optimise.error} />}

      {/* Control bar */}
      <div className="card flex flex-wrap items-center gap-x-4 gap-y-3 px-4 py-3">
        <div className="flex items-center gap-2">
          <Button
            variant={running ? 'secondary' : 'primary'}
            size="sm"
            icon={running ? Pause : Play}
            onClick={() => setRunning((r) => !r)}
          >
            {running ? 'Pause' : 'Play'}
          </Button>
          <Button variant="ghost" size="sm" icon={RotateCcw} onClick={resetClock}>
            Reset
          </Button>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-faint text-xs">Clock</span>
          <span className="ticker-value rounded-md bg-[rgb(var(--surface-sunken))] px-2.5 py-1 text-sm font-semibold">
            {formatSimClock(clockHours)}
          </span>
        </div>

        <div className="flex items-center gap-1.5" role="group" aria-label="Simulation speed">
          {TIME_SCALES.map((scale) => (
            <button
              key={scale.id}
              type="button"
              title={scale.note}
              onClick={() => setScaleId(scale.id)}
              className={cx(
                'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                scale.id === scaleId
                  ? 'bg-primary-600 text-white'
                  : 'text-[rgb(var(--text-secondary))] hover:bg-[rgb(var(--surface-sunken))]',
              )}
            >
              {scale.label}
            </button>
          ))}
        </div>

        <Button
          size="sm"
          variant={split ? 'primary' : 'secondary'}
          icon={split ? Maximize2 : Columns2}
          onClick={() => setSplit((s) => !s)}
          disabled={!usingPlan}
          title={
            usingPlan
              ? 'Baseline and optimised side by side on one clock'
              : 'Run the optimiser first — there is nothing to compare against yet'
          }
        >
          {split ? 'Single map' : 'Split compare'}
        </Button>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Select
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="w-40"
            aria-label="Season"
            options={[
              { value: '', label: 'Annual mean' },
              ...MONTHS.map((m) => ({ value: String(m.value), label: m.label })),
            ]}
          />
          <Badge tone={usingPlan ? 'eco' : 'neutral'} icon={usingPlan ? Sparkles : ShipIcon}>
            {usingPlan
              ? `Optimised · ${planResult.algorithm.toUpperCase()}`
              : 'Baseline · design speed'}
          </Badge>
          <Button
            size="sm"
            variant="eco"
            icon={Sparkles}
            loading={optimise.loading}
            onClick={runOptimiser}
          >
            {usingPlan ? 'Re-optimise' : 'Optimise & sail'}
          </Button>
        </div>
      </div>

      {/* Maps + panel */}
      <div className="flex flex-col gap-3 xl:flex-row">
        <div className="card relative min-w-0 flex-1 overflow-hidden p-0">
          <div className={cx('relative', mapHeight)}>
            {loading ? (
              <div className="text-faint grid h-full place-items-center text-sm">
                Loading the lane network…
              </div>
            ) : split ? (
              <div className="grid h-full grid-cols-1 gap-px bg-[rgb(var(--border-strong))] lg:grid-cols-2">
                <VoyageMap
                  viewport={viewport}
                  network={network}
                  ships={baselineShips}
                  clockRef={clockRef}
                  running={running}
                  timeScale={timeScale.hoursPerSecond}
                  layers={layers}
                  onTick={onBaselineTick}
                  badge="Baseline · design speed, today's bunker"
                />
                <VoyageMap
                  viewport={viewport}
                  network={network}
                  ships={planShips}
                  clockRef={clockRef}
                  running={running}
                  timeScale={timeScale.hoursPerSecond}
                  layers={layers}
                  selectedId={selectedId}
                  dimmedIds={dimmedIds}
                  onSelect={setSelectedId}
                  onTick={onTick}
                  badge={`Optimised · ${planResult?.algorithm_name ?? ''}`}
                  badgeTone="eco"
                  legendFuels={legendFuels}
                />
              </div>
            ) : (
              <VoyageMap
                viewport={viewport}
                network={network}
                ships={ships}
                clockRef={clockRef}
                running={running}
                timeScale={timeScale.hoursPerSecond}
                layers={layers}
                selectedId={selectedId}
                dimmedIds={dimmedIds}
                activeLanes={activeLanes}
                activePorts={activePorts}
                onSelect={setSelectedId}
                onTick={onTick}
                onSelectLane={(name) => {
                  const match = ships.find((s) => s.laneName === name)
                  if (match) setSelectedId(match.id)
                }}
                legendFuels={legendFuels}
              />
            )}

            {!split && (
              <>
                <div className="absolute left-3 top-3 flex flex-wrap gap-1.5">
                  {Object.entries(MAP_VIEWS).map(([key, view]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setBox(view.box)}
                      className="rounded-md bg-black/70 px-2 py-1 text-[0.7rem] font-medium text-slate-100 transition-colors hover:bg-black/85"
                    >
                      {view.label}
                    </button>
                  ))}
                </div>
                <p className="absolute bottom-3 right-3 rounded-md bg-black/60 px-2 py-1 text-[0.65rem] text-slate-300">
                  Drag to pan · scroll to zoom · space to pause
                </p>
              </>
            )}

            <div className="absolute right-3 top-3 z-10 flex flex-col gap-1.5">
              <button
                type="button"
                onClick={() => zoomBy(0.7)}
                aria-label="Zoom in"
                className="rounded-md bg-black/70 p-1.5 text-slate-100 transition-colors hover:bg-black/85"
              >
                <ZoomIn size={15} />
              </button>
              <button
                type="button"
                onClick={() => zoomBy(1.43)}
                aria-label="Zoom out"
                className="rounded-md bg-black/70 p-1.5 text-slate-100 transition-colors hover:bg-black/85"
              >
                <ZoomOut size={15} />
              </button>
              <button
                type="button"
                onClick={centreOnSelected}
                disabled={!selectedId}
                aria-label="Centre on selected vessel"
                className="rounded-md bg-black/70 p-1.5 text-slate-100 transition-colors hover:bg-black/85 disabled:opacity-40"
              >
                <Crosshair size={15} />
              </button>
            </div>
          </div>

          {/* Live ticker */}
          <div
            className="grid grid-cols-2 gap-3 border-t px-4 py-3 sm:grid-cols-3 lg:grid-cols-6"
            style={{ borderColor: 'rgb(var(--border-subtle))' }}
          >
            <Ticker
              label="At sea"
              value={`${totals.atSea}/${totals.vessels}`}
              icon={ShipIcon}
              tone="text-primary-400"
            />
            <Ticker label="Alongside" value={totals.inPort} icon={Anchor} tone="text-slate-400" />
            <Ticker
              label="Mean speed"
              value={totals.avgSpeed.toFixed(1)}
              unit="kn"
              icon={Gauge}
              tone="text-amber-400"
            />
            <Ticker
              label="Fuel burnt"
              value={compact(totals.fuel)}
              unit="t"
              icon={Droplets}
              tone="text-sky-400"
              delta={divergence ? `−${divergence.fuel.toFixed(0)}%` : undefined}
            />
            <Ticker
              label="CO₂e emitted"
              value={compact(totals.co2)}
              unit="t"
              icon={Leaf}
              tone="text-eco-400"
              delta={divergence ? `−${divergence.co2.toFixed(0)}%` : undefined}
            />
            <Ticker
              label="Voyage cost"
              value={usd(totals.cost, { compact: true })}
              icon={Wind}
              tone="text-violet-400"
              delta={divergence ? `−${divergence.cost.toFixed(0)}%` : undefined}
            />
          </div>

          {split && divergence && (
            <div
              className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t bg-eco-50/60 px-4 py-3 text-sm dark:bg-eco-950/20"
              style={{ borderColor: 'rgb(var(--border-subtle))' }}
            >
              <span className="flex items-center gap-2 font-semibold text-eco-700 dark:text-eco-300">
                <TrendingDown size={16} aria-hidden />
                Gap after {formatSimClock(clockHours).toLowerCase()}
              </span>
              <span className="numeric">
                {num(divergence.absFuel, 0)} t less bunker per vessel
              </span>
              <span className="numeric">{num(divergence.absCo2, 0)} t less CO₂e per vessel</span>
              <span className="text-faint text-xs">
                Compared per vessel, not per fleet — the two sides carry different numbers of
                ships, and totals alone would flatter whichever has fewer.
              </span>
            </div>
          )}
        </div>

        {/* Side panel */}
        <div className="shrink-0 space-y-3 xl:w-80">
          <div className="card p-4">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Layers size={15} aria-hidden /> Map layers
            </h2>
            <div className="mt-3 space-y-3">
              <LayerToggles layers={layers} setLayers={setLayers} />
              <div className="grid grid-cols-2 gap-2">
                <Select
                  value={fuelFilter}
                  onChange={(e) => setFuelFilter(e.target.value)}
                  options={fuelOptions}
                  aria-label="Filter by fuel"
                />
                <Select
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}
                  options={typeOptions}
                  aria-label="Filter by vessel class"
                />
              </div>
            </div>
          </div>

          {ciiSummary && (
            <div className="card p-4">
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="text-sm font-semibold">Carbon intensity</h2>
                <Badge tone={ciiSummary.compliant_pct >= 60 ? 'eco' : 'warning'}>
                  {pct(ciiSummary.compliant_pct, 0)} at C or better
                </Badge>
              </div>
              <div className="mt-3 flex h-2.5 overflow-hidden rounded-full">
                {['A', 'B', 'C', 'D', 'E'].map((band) => {
                  const n = ciiSummary.distribution[band] ?? 0
                  if (!n) return null
                  return (
                    <div
                      key={band}
                      className="h-full"
                      style={{
                        width: `${(n / Math.max(ciiSummary.rated_count, 1)) * 100}%`,
                        backgroundColor: ciiColor(band),
                      }}
                      title={`${n} vessel${n === 1 ? '' : 's'} rated ${band}`}
                    />
                  )
                })}
              </div>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                {['A', 'B', 'C', 'D', 'E'].map((band) => (
                  <span key={band} className="text-faint flex items-center gap-1 text-xs">
                    <span
                      className="h-2 w-2 rounded-sm"
                      style={{ backgroundColor: ciiColor(band) }}
                      aria-hidden
                    />
                    {band} · {ciiSummary.distribution[band] ?? 0}
                  </span>
                ))}
              </div>
              {ciiSummary.at_risk?.length > 0 && (
                <p className="text-faint mt-2.5 text-xs">
                  {ciiSummary.at_risk.length} vessel
                  {ciiSummary.at_risk.length === 1 ? '' : 's'} at D or E on this plan — three
                  consecutive years at D, or one at E, forces a corrective action plan.
                </p>
              )}
            </div>
          )}

          <div className="card flex flex-col p-0">
            <header
              className="flex items-center justify-between gap-2 border-b px-4 py-3"
              style={{ borderColor: 'rgb(var(--border-subtle))' }}
            >
              <h2 className="text-sm font-semibold">Fleet ({visibleShips.length})</h2>
              {selectedId && (
                <button
                  type="button"
                  onClick={() => setSelectedId(null)}
                  className="text-faint text-xs underline-offset-2 hover:underline"
                >
                  Clear
                </button>
              )}
            </header>
            <div className="max-h-[24rem] space-y-1.5 overflow-y-auto p-2 xl:max-h-[calc(100vh-40rem)]">
              {visibleShips.length === 0 && (
                <p className="text-faint px-2 py-6 text-center text-sm">
                  No vessels match the current filter.
                </p>
              )}
              {visibleShips.map((ship) => {
                const snapshot = snapshotById[ship.id]
                if (!snapshot) return null
                return (
                  <VesselRow
                    key={ship.id}
                    snapshot={snapshot}
                    selected={ship.id === selectedId}
                    onSelect={setSelectedId}
                  />
                )
              })}
            </div>
          </div>

          {!usingPlan && !loading && (
            <Alert tone="info" title="Baseline fleet">
              Vessels are sailing their home lanes at design speed on today&apos;s default bunker.
              Run the optimiser to redeploy them, then switch to split view to watch the gap open
              up.
            </Alert>
          )}

          {layers.eca && network.ecaLanes.some((l) => l.eca_fraction > 0) && (
            <div className="card p-4">
              <h2 className="text-sm font-semibold">Emission control areas</h2>
              <p className="text-faint mt-1 text-xs">
                Fuel sulphur is capped at 0.10% inside one, against 0.50% globally. A ship on
                residual fuel has to switch to distillate for that stretch, and the optimiser
                prices the switch.
              </p>
              <ul className="mt-2.5 space-y-1 text-xs">
                {network.ecaLanes
                  .filter((l) => l.eca_fraction > 0)
                  .map((lane) => (
                    <li key={lane.name} className="flex items-center justify-between gap-2">
                      <span className="truncate">{lane.name}</span>
                      <span className="numeric shrink-0 text-amber-600 dark:text-amber-400">
                        {pct(lane.eca_fraction * 100, 0)} · {num(lane.eca_nm)} nm
                      </span>
                    </li>
                  ))}
              </ul>
            </div>
          )}

          {layers.weather && network.lanes.length > 0 && (
            <div className="card p-4">
              <h2 className="text-sm font-semibold">Roughest lanes</h2>
              <p className="text-faint mt-1 text-xs">
                Annual-mean Beaufort. The optimiser charges a{' '}
                <span className="numeric">1 + 0.02·B^1.5</span> penalty on propulsion fuel.
              </p>
              <ul className="mt-2.5 space-y-1 text-xs">
                {[...network.lanes]
                  .sort((a, b) => b.typical_beaufort - a.typical_beaufort)
                  .slice(0, 5)
                  .map((lane) => (
                    <li key={lane.name} className="flex items-center justify-between gap-2">
                      <span className="truncate">{lane.name}</span>
                      <span className="numeric text-faint shrink-0">
                        {lane.typical_beaufort.toFixed(1)} · {beaufortLabel(lane.typical_beaufort)}
                      </span>
                    </li>
                  ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
