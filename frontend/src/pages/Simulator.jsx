/**
 * Live voyage simulator.
 *
 * The map is the product. Everything else in the app produces numbers; this is
 * where an operator can see what the numbers mean — which ship is where, how
 * fast it is going, what it is burning, and how the optimiser's plan differs
 * from sailing everything flat out at design speed.
 */
import {
  Anchor,
  Crosshair,
  Droplets,
  Gauge,
  Layers,
  Leaf,
  Pause,
  Play,
  RotateCcw,
  Ship as ShipIcon,
  Sparkles,
  Wind,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import ShipLayer from '../components/ShipLayer'
import WorldMap, { useMapViewport } from '../components/WorldMap'
import { Alert, Badge, Button, Checkbox, ErrorState, Select, cx } from '../components/ui'
import { MAP_VIEWS, PORTS, buildLaneGeometry, project } from '../data/geography'
import { useAsync, useFetch } from '../hooks/useApi'
import api from '../lib/api'
import { OPTIMIZER_PRESETS, beaufortLabel, fuelColor } from '../lib/domain'
import { compact, num, pct, usd } from '../lib/format'
import { setActivePlan, useActivePlan } from '../lib/planStore'
import {
  TIME_SCALES,
  formatDuration,
  formatSimClock,
  shipsFromPlan,
  shipsFromRegistry,
} from '../lib/simulation'

// A fresh `[]` per render would invalidate every downstream useMemo.
const EMPTY = []

/* -------------------------------------------------------------------------- */
/* Small pieces                                                                */
/* -------------------------------------------------------------------------- */
function Ticker({ label, value, unit, icon: Icon, tone = 'text-primary-400' }) {
  return (
    <div className="flex items-center gap-2.5">
      <Icon size={16} className={cx('shrink-0', tone)} aria-hidden />
      <div className="min-w-0">
        <p className="text-faint text-[0.68rem] font-medium uppercase tracking-wide">{label}</p>
        <p className="ticker-value truncate text-sm font-semibold">
          {value}
          {unit && <span className="text-faint ml-1 text-xs font-normal">{unit}</span>}
        </p>
      </div>
    </div>
  )
}

function VesselRow({ snapshot, ship, selected, onSelect }) {
  const color = fuelColor(snapshot.fuelType)
  return (
    <button
      type="button"
      onClick={() => onSelect(selected ? null : snapshot.id)}
      className={cx(
        'w-full rounded-lg border p-2.5 text-left transition-colors',
        selected
          ? 'border-primary-500 bg-primary-50 dark:bg-primary-950/40'
          : 'border-transparent hover:bg-[rgb(var(--surface-sunken))]',
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
      {selected && ship && (
        <dl className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1 border-t pt-2 text-xs"
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
  const registry = useFetch((signal) => api.optimization.registry({ signal }), [])
  const fuels = useFetch((signal) => api.scenarios.fuels({ signal }), [])
  const active = useActivePlan()
  const optimise = useAsync((signal, body) => api.optimization.optimize(body, { signal }))

  const [running, setRunning] = useState(true)
  const [scaleId, setScaleId] = useState('faster')
  const [selectedId, setSelectedId] = useState(null)
  const [fuelFilter, setFuelFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [snapshots, setSnapshots] = useState([])
  const [clockHours, setClockHours] = useState(0)
  const [panelOpen, setPanelOpen] = useState(true)
  const [layers, setLayers] = useState({
    trails: true,
    names: false,
    portLabels: true,
    chokepoints: true,
    graticule: true,
    weather: false,
  })

  const clockRef = useRef({ hours: 0 })
  const viewport = useMapViewport(MAP_VIEWS.indianOcean.box)
  const { setBox, pxPerUnit, zoomAt, svgRef } = viewport

  /* ---- data ------------------------------------------------------------- */
  const lanes = registry.data?.lanes ?? EMPTY
  const lanesByName = useMemo(
    () => Object.fromEntries(lanes.map((lane) => [lane.name, lane])),
    [lanes],
  )
  const geometries = useMemo(() => {
    const out = {}
    lanes.forEach((lane) => {
      const geometry = buildLaneGeometry(lane)
      if (geometry) out[lane.name] = geometry
    })
    return out
  }, [lanes])

  const fuelsByName = useMemo(
    () => Object.fromEntries((fuels.data ?? EMPTY).map((f) => [f.name, f])),
    [fuels.data],
  )

  const planResult = active.result
  const ships = useMemo(() => {
    if (planResult?.plan?.assignments?.length) return shipsFromPlan(planResult, lanesByName)
    if (registry.data && fuels.data) return shipsFromRegistry(registry.data, fuelsByName)
    return []
  }, [planResult, lanesByName, registry.data, fuels.data, fuelsByName])

  /* ---- filtering -------------------------------------------------------- */
  const dimmedIds = useMemo(() => {
    const dimmed = new Set()
    ships.forEach((ship) => {
      const fuelOk = fuelFilter === 'all' || ship.fuelType === fuelFilter
      const typeOk = typeFilter === 'all' || ship.vesselType === typeFilter
      if (!fuelOk || !typeOk) dimmed.add(ship.id)
    })
    return dimmed
  }, [ships, fuelFilter, typeFilter])

  const visibleShips = useMemo(
    () => ships.filter((ship) => !dimmedIds.has(ship.id)),
    [ships, dimmedIds],
  )
  const activeLanes = useMemo(
    () => new Set(visibleShips.map((ship) => ship.laneName)),
    [visibleShips],
  )
  const activePorts = useMemo(() => {
    const set = new Set()
    visibleShips.forEach((ship) => {
      const lane = lanesByName[ship.laneName]
      if (lane) {
        set.add(lane.origin)
        set.add(lane.destination)
      }
    })
    return set
  }, [visibleShips, lanesByName])

  const ports = useMemo(
    () => Object.entries(PORTS).map(([name, p]) => ({ name, ...p })),
    [],
  )

  /* ---- clock ------------------------------------------------------------ */
  const timeScale = TIME_SCALES.find((s) => s.id === scaleId) ?? TIME_SCALES[2]

  const onTick = useCallback((hours, next) => {
    setClockHours(hours)
    setSnapshots(next)
  }, [])

  const resetClock = useCallback(() => {
    clockRef.current.hours = 0
    setClockHours(0)
  }, [])

  // Space toggles play/pause, the way every media player does.
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
  const totals = useMemo(() => {
    const rows = snapshots.filter((s) => visibleIds.has(s.id))
    const atSea = rows.filter((s) => !s.berthed)
    return {
      vessels: rows.length,
      atSea: atSea.length,
      inPort: rows.length - atSea.length,
      fuel: rows.reduce((a, s) => a + s.fuelTons, 0),
      co2: rows.reduce((a, s) => a + s.co2Tons, 0),
      cost: rows.reduce((a, s) => a + s.costUsd, 0),
      avgSpeed: atSea.length
        ? atSea.reduce((a, s) => a + s.speedKnots, 0) / atSea.length
        : 0,
    }
  }, [snapshots, visibleIds])

  const snapshotById = useMemo(
    () => Object.fromEntries(snapshots.map((s) => [s.id, s])),
    [snapshots],
  )
  /* ---- actions ---------------------------------------------------------- */
  const runOptimiser = useCallback(async () => {
    const preset = OPTIMIZER_PRESETS[0].config
    const result = await optimise.run({
      ...preset,
      algorithm: 'qpso',
      seed: 42,
      include_plan: true,
    })
    if (result) {
      setActivePlan(result, 'simulator')
      resetClock()
    }
  }, [optimise, resetClock])

  const centreOnSelected = useCallback(() => {
    const snapshot = snapshotById[selectedId]
    const geometry = snapshot && geometries[snapshot.laneName]
    if (!geometry) return
    const lane = lanesByName[snapshot.laneName]
    const [ox, oy] = project([PORTS[lane.origin].lat, PORTS[lane.origin].lon])
    const [dx, dy] = project([PORTS[lane.destination].lat, PORTS[lane.destination].lon])
    const pad = 12
    const x = Math.min(ox, dx) - pad
    const y = Math.min(oy, dy) - pad
    const w = Math.max(Math.abs(dx - ox) + pad * 2, 24)
    const h = Math.max(Math.abs(dy - oy) + pad * 2, 18)
    setBox([x, y, w, h])
  }, [snapshotById, selectedId, geometries, lanesByName, setBox])

  const zoomByButton = useCallback(
    (factor) => {
      const rect = svgRef.current?.getBoundingClientRect()
      if (!rect) return
      zoomAt(factor, rect.left + rect.width / 2, rect.top + rect.height / 2)
    },
    [svgRef, zoomAt],
  )

  const fuelOptions = useMemo(() => {
    const present = [...new Set(ships.map((s) => s.fuelType))]
    return [{ value: 'all', label: 'All fuels' }, ...present.map((f) => ({ value: f, label: f }))]
  }, [ships])

  const typeOptions = useMemo(() => {
    const present = [...new Set(ships.map((s) => s.vesselType))]
    return [{ value: 'all', label: 'All classes' }, ...present.map((t) => ({ value: t, label: t }))]
  }, [ships])

  const usingPlan = Boolean(planResult?.plan?.assignments?.length)
  const loading = registry.loading || fuels.loading
  const error = registry.error || fuels.error

  /* ---- render ----------------------------------------------------------- */
  return (
    <div className="space-y-3">
      {error && <ErrorState error={error} onRetry={registry.refetch} />}
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

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Badge tone={usingPlan ? 'eco' : 'neutral'} icon={usingPlan ? Sparkles : ShipIcon}>
            {usingPlan
              ? `Optimised plan · ${planResult.algorithm_name}`
              : 'Registry baseline · design speed'}
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

      {/* Map + panel */}
      <div className="flex flex-col gap-3 xl:flex-row">
        <div className="card relative min-w-0 flex-1 overflow-hidden p-0">
          <div className="relative h-[58vh] min-h-[380px] xl:h-[calc(100vh-19rem)]">
            {loading ? (
              <div className="text-faint grid h-full place-items-center text-sm">
                Loading fleet registry…
              </div>
            ) : (
              <WorldMap
                viewport={viewport}
                lanes={lanes}
                geometries={geometries}
                ports={ports}
                activeLanes={activeLanes}
                activePorts={activePorts}
                showPortLabels={layers.portLabels}
                showChokepoints={layers.chokepoints}
                showGraticule={layers.graticule}
                laneColorBy={layers.weather ? 'weather' : 'uniform'}
                paused={!running}
                onSelectLane={(name) => {
                  const match = ships.find((s) => s.laneName === name)
                  if (match) setSelectedId(match.id)
                }}
              >
                <ShipLayer
                  ships={ships}
                  geometries={geometries}
                  clockRef={clockRef}
                  running={running}
                  timeScale={timeScale.hoursPerSecond}
                  pxPerUnit={pxPerUnit}
                  selectedId={selectedId}
                  dimmedIds={dimmedIds}
                  showTrails={layers.trails}
                  showNames={layers.names}
                  onSelect={setSelectedId}
                  onTick={onTick}
                />
              </WorldMap>
            )}

            {/* Zoom presets, floating over the map */}
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

            <div className="absolute right-3 top-3 flex flex-col gap-1.5">
              <button
                type="button"
                onClick={() => zoomByButton(0.7)}
                aria-label="Zoom in"
                className="rounded-md bg-black/70 p-1.5 text-slate-100 transition-colors hover:bg-black/85"
              >
                <ZoomIn size={15} />
              </button>
              <button
                type="button"
                onClick={() => zoomByButton(1.43)}
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

            {/* Fuel legend */}
            <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-black/70 px-2.5 py-1.5">
              {[...new Set(ships.map((s) => s.fuelType))].map((fuel) => (
                <span key={fuel} className="flex items-center gap-1.5 text-[0.7rem] text-slate-100">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: fuelColor(fuel) }}
                    aria-hidden
                  />
                  {fuel}
                </span>
              ))}
            </div>
            <p className="absolute bottom-3 right-3 rounded-md bg-black/60 px-2 py-1 text-[0.65rem] text-slate-300">
              Drag to pan · scroll to zoom · space to pause
            </p>
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
            />
            <Ticker
              label="CO₂e emitted"
              value={compact(totals.co2)}
              unit="t"
              icon={Leaf}
              tone="text-eco-400"
            />
            <Ticker
              label="Voyage cost"
              value={usd(totals.cost, { compact: true })}
              icon={Wind}
              tone="text-violet-400"
            />
          </div>
        </div>

        {/* Side panel */}
        <div className={cx('shrink-0 space-y-3', panelOpen ? 'xl:w-80' : 'xl:w-auto')}>
          <div className="card p-4">
            <div className="flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <Layers size={15} aria-hidden /> Map layers
              </h2>
              <button
                type="button"
                onClick={() => setPanelOpen((o) => !o)}
                className="text-faint text-xs underline-offset-2 hover:underline xl:hidden"
              >
                {panelOpen ? 'Hide' : 'Show'}
              </button>
            </div>
            {panelOpen && (
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
            )}
          </div>

          {panelOpen && (
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
                    Clear selection
                  </button>
                )}
              </header>
              <div className="max-h-[26rem] space-y-1.5 overflow-y-auto p-2 xl:max-h-[calc(100vh-33rem)]">
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
                      ship={ship}
                      snapshot={snapshot}
                      selected={ship.id === selectedId}
                      onSelect={setSelectedId}
                    />
                  )
                })}
              </div>
            </div>
          )}

          {panelOpen && usingPlan && planResult.improvement_vs_baseline && (
            <Alert tone="success" title="Against the unoptimised baseline">
              <ul className="mt-1 space-y-0.5 text-xs">
                {Object.entries(planResult.improvement_vs_baseline).map(([key, value]) => (
                  <li key={key} className="flex justify-between gap-3">
                    <span>{key.replace(/_/g, ' ')}</span>
                    <span className="numeric font-semibold">{pct(value.percent_saving)}</span>
                  </li>
                ))}
              </ul>
            </Alert>
          )}

          {panelOpen && !usingPlan && !loading && (
            <Alert tone="info" title="Baseline fleet">
              Vessels are sailing their home lanes at design speed on today&apos;s default bunker.
              Run the optimiser to see the same fleet re-deployed.
            </Alert>
          )}

          {panelOpen && lanes.length > 0 && layers.weather && (
            <div className="card p-4">
              <h2 className="text-sm font-semibold">Sea state on lanes</h2>
              <p className="text-faint mt-1 text-xs">
                Annual-mean Beaufort. The optimiser charges a{' '}
                <span className="numeric">1 + 0.02·B^1.5</span> penalty on propulsion fuel.
              </p>
              <ul className="mt-2.5 space-y-1 text-xs">
                {[...lanes]
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
