/**
 * LIVE FLEET — the dashboard hero.
 *
 * One map, one toggle, one interaction. Everything this card used to carry
 * around the map — layer filters, a fuel select, four view tabs, a KPI strip,
 * a lane ranking, health meters, an insight feed and a provenance bar — was
 * removed on purpose. The map communicates the product; a frame of controls
 * around it communicates a settings screen.
 *
 * The one interaction that remains is OPTIMIZE & SAIL. Click a vessel, run the
 * solver, watch its lane turn green, apply the plan. Every figure in that
 * sequence is the optimiser's own output compared against the baseline
 * deployment — nothing here is estimated in the browser.
 */
import { Radar, Sparkles, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import WorldMap, { useMapViewport } from '../WorldMap'
import { FlowLayer, VesselLayer } from './NetworkMapLayers'
import { Button, Skeleton, cx } from '../ui'
import { MAP_VIEWS } from '../../data/geography'
import { num, pct, usd } from '../../lib/format'
import { buildNetworkIntel } from '../../lib/networkIntel'

const EMPTY = []

/**
 * A metric that changed. Green when it fell, amber when it rose, and plainly
 * "no change" when the solver left this vessel where it was — a real 0.0%
 * dressed up with an arrow reads as a broken number.
 */
function Delta({ label, before, after, format }) {
  if (before == null || after == null || before === 0) return null
  const change = ((after - before) / before) * 100
  const flat = Math.abs(change) < 0.05
  const better = change < 0
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <span className="text-faint text-[0.7rem] uppercase tracking-wide">{label}</span>
      <span className="flex items-baseline gap-2">
        <span className="numeric text-sm font-semibold">{format(after)}</span>
        {flat ? (
          <span className="text-faint text-xs">no change</span>
        ) : (
          <span
            className={cx(
              'numeric text-xs font-semibold',
              better ? 'text-eco-500' : 'text-amber-500',
            )}
          >
            {better ? '↓' : '↑'} {pct(Math.abs(change))}
          </span>
        )}
      </span>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* The one interaction                                                         */
/* -------------------------------------------------------------------------- */
function VesselPanel({ vessel, optimised, improvement, phase, onOptimise, onApply, onClose }) {
  // A fleet optimiser moves ships between lanes. When it does, this vessel's
  // fuel is not comparable to its old fuel — it is sailing a different
  // distance — so the new lane is named rather than letting a red +260% imply
  // the solver made things worse.
  const reassigned = optimised && optimised.lane !== vessel.lane
  const fleetSaving = improvement?.fuel_consumption_tons?.percent_saving ?? null
  // Cost first — it is what the fleet is optimised for.
  const fleetCostSaving = improvement?.operational_cost_usd?.percent_saving ?? null

  return (
    <div
      className="animate-fade-in w-full rounded-xl border p-4 shadow-pop backdrop-blur-sm lg:absolute lg:right-3 lg:top-3 lg:z-10 lg:w-[19rem]"
      style={{
        backgroundColor: 'rgb(var(--surface-card) / 0.97)',
        borderColor: 'rgb(var(--border-strong))',
      }}
      role="region"
      aria-label={vessel.name}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{vessel.name}</p>
          <p className="text-faint truncate text-xs">{vessel.route}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="text-faint shrink-0 rounded p-0.5 transition-colors hover:text-[rgb(var(--text-primary))]"
        >
          <X size={14} />
        </button>
      </div>

      {/* Current state — four figures, no cards, no chrome. */}
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5">
        <div>
          <p className="numeric text-lg font-semibold tracking-tight">{num(vessel.speed, 1)}</p>
          <p className="text-faint text-[0.66rem] uppercase tracking-wide">kn</p>
        </div>
        <div>
          <p className="numeric text-lg font-semibold tracking-tight">
            {num(vessel.voyageDays * 24, 1)}
          </p>
          <p className="text-faint text-[0.66rem] uppercase tracking-wide">ETA hours</p>
        </div>
        <div>
          <p className="numeric text-lg font-semibold tracking-tight">{num(vessel.fuelTons, 0)} t</p>
          <p className="text-faint text-[0.66rem] uppercase tracking-wide">Fuel</p>
        </div>
        <div>
          <p className="numeric text-lg font-semibold tracking-tight">{num(vessel.co2Tons, 0)} t</p>
          <p className="text-faint text-[0.66rem] uppercase tracking-wide">CO₂</p>
        </div>
      </div>

      {/* The WOW. Three states: offer, thinking, result. */}
      {phase === 'analyzing' ? (
        <div className="mt-4 flex items-center gap-2.5">
          <span className="relative flex h-2 w-2" aria-hidden>
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary-500 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-primary-500" />
          </span>
          <span className="text-xs font-medium uppercase tracking-[0.14em] text-primary-500">
            Analyzing…
          </span>
        </div>
      ) : optimised ? (
        <div className="mt-4">
          <p className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-eco-500">
            Optimized
          </p>
          {reassigned && (
            <p className="text-faint mt-1 text-xs">
              Reassigned to {optimised.route} · {num(optimised.speed, 1)} kn
            </p>
          )}
          <div
            className="mt-1.5 divide-y"
            style={{ borderColor: 'rgb(var(--border-subtle))' }}
          >
            <Delta
              label="Fuel"
              before={vessel.fuelTons}
              after={optimised.fuelTons}
              format={(v) => `${num(v, 0)} t`}
            />
            <Delta
              label="CO₂"
              before={vessel.co2Tons}
              after={optimised.co2Tons}
              format={(v) => `${num(v, 0)} t`}
            />
            <Delta
              label="Cost"
              before={vessel.costUsd}
              after={optimised.costUsd}
              format={(v) => usd(v, { compact: true })}
            />
          </div>
          {/* What applying actually buys, fleet-wide. A panel that showed
              only this ship's line would read as a regression whenever the
              solver traded one vessel's voyage for a better whole. */}
          {(fleetCostSaving != null || fleetSaving != null) && (
            <p className="mt-2.5 text-xs">
              <span className="text-faint">Whole fleet</span>{' '}
              <span className="numeric font-semibold text-eco-500">
                {fleetCostSaving != null && `↓ ${pct(fleetCostSaving)} cost`}
                {fleetCostSaving != null && fleetSaving != null && ' · '}
                {fleetSaving != null && `↓ ${pct(fleetSaving)} fuel`}
              </span>
            </p>
          )}
          <Button className="mt-3 w-full" variant="eco" icon={Radar} onClick={onApply}>
            Apply plan
          </Button>
        </div>
      ) : (
        <Button className="mt-4 w-full" icon={Sparkles} onClick={onOptimise}>
          Optimize &amp; sail
        </Button>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Hero                                                                        */
/* -------------------------------------------------------------------------- */
export default function NetworkSection({
  network,
  baseline,
  plan,
  improvement,
  loading,
  optimising = false,
  onOptimiseVessel,
  onApplyPlan,
  onOpenSimulator,
}) {
  const viewport = useMapViewport(MAP_VIEWS.indianOcean.box)

  // `network` shows the fleet as it sails today; `optimize` shows the solver's
  // plan over the top. Two states, one control — not four view tabs.
  const [mode, setMode] = useState('network')
  const [selectedId, setSelectedId] = useState(null)
  const [hovered, setHovered] = useState(null)

  const baseIntel = useMemo(
    () => buildNetworkIntel({ plan: null, baseline, lanes: network.lanes, ports: network.ports }),
    [baseline, network.lanes, network.ports],
  )

  const planIntel = useMemo(
    () =>
      plan
        ? buildNetworkIntel({ plan, baseline, lanes: network.lanes, ports: network.ports })
        : null,
    [plan, baseline, network.lanes, network.ports],
  )

  // Which deployment the map draws. Optimize mode falls back to the baseline
  // until a plan exists, so the toggle never blanks the map.
  const showOptimised = mode === 'optimize' && planIntel
  const intel = showOptimised ? planIntel : baseIntel

  const laneStates = useMemo(
    () => Object.fromEntries(intel.lanes.map((lane) => [lane.name, lane.state])),
    [intel.lanes],
  )

  // In optimize mode the lanes the solver actually improved are the only ones
  // emphasised, so the change reads at a glance instead of needing a legend.
  const emphasis = useMemo(() => {
    if (!showOptimised) return EMPTY
    return planIntel.lanes.filter((lane) => lane.state === 'optimised').map((lane) => lane.name)
  }, [showOptimised, planIntel])

  const vessel = selectedId ? baseIntel.vessels.find((v) => v.id === selectedId) : null
  const optimisedVessel =
    selectedId && planIntel ? planIntel.vessels.find((v) => v.id === selectedId) : null

  const phase = optimising ? 'analyzing' : 'idle'

  const runOptimise = async () => {
    const ok = await onOptimiseVessel?.()
    if (ok) setMode('optimize')
  }

  return (
    <section className="flex flex-col">
      {/* Title row — a heading, a count, one way out. No card header. */}
      <div className="mb-2.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-xs font-semibold uppercase tracking-[0.16em]">Live fleet</h2>
        <p className="text-faint numeric text-xs">
          {loading ? '—' : `${intel.kpis.vessels} vessels · ${network.lanes.length} routes`}
        </p>
        <div className="ml-auto flex items-center gap-1.5">
          {/* The only map control. */}
          <div
            className="flex items-center rounded-lg border p-0.5"
            style={{ borderColor: 'rgb(var(--border-subtle))' }}
            role="group"
            aria-label="Map mode"
          >
            {[
              ['network', 'Network'],
              ['optimize', 'Optimize'],
            ].map(([id, label]) => (
              <button
                key={id}
                type="button"
                aria-pressed={mode === id}
                onClick={() => setMode(id)}
                className={cx(
                  'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  mode === id
                    ? 'bg-primary-600 text-white'
                    : 'text-faint hover:text-[rgb(var(--text-primary))]',
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <Button size="sm" variant="secondary" icon={Radar} onClick={onOpenSimulator}>
            Open Digital Twin
          </Button>
        </div>
      </div>

      {/* The map. Tall on purpose — it is the product. */}
      <div className="relative overflow-hidden rounded-xl border" style={{ borderColor: 'rgb(var(--border-subtle))' }}>
        <div className="h-[24rem] sm:h-[30rem] lg:h-[34rem]">
          {loading ? (
            <Skeleton className="h-full w-full" />
          ) : (
            <WorldMap
              viewport={viewport}
              lanes={network.lanes}
              geometries={network.geometries}
              ports={network.ports}
              chokepoints={EMPTY}
              showPortLabels
              showChokepoints={false}
              showGraticule
              laneStates={laneStates}
              onSelectLane={undefined}
              onSelectPort={undefined}
            >
              <FlowLayer
                lanes={network.lanes}
                geometries={network.geometries}
                laneStates={laneStates}
                running
                emphasis={emphasis}
              />
              <VesselLayer
                vessels={intel.vessels}
                geometries={network.geometries}
                selectedId={selectedId}
                onSelect={(v) => setSelectedId(v.id)}
                onHover={setHovered}
              />
            </WorldMap>
          )}

          {/* One line, not a tooltip cloud. */}
          {hovered && !vessel && (
            <div
              className="pointer-events-none absolute left-2.5 top-2.5 rounded-md px-2.5 py-1.5 text-[0.7rem] text-slate-100"
              style={{ backgroundColor: 'rgb(4 18 31 / 0.9)' }}
            >
              <span className="font-semibold">{hovered.name}</span>
              <span className="text-slate-400"> · {hovered.speed} kn</span>
            </div>
          )}
        </div>

        {/* On a phone the panel stacks below the map rather than covering it. */}
        {vessel && (
          <div className="p-3 lg:p-0">
            <VesselPanel
              vessel={vessel}
              optimised={optimisedVessel}
              improvement={improvement}
              phase={phase}
              onOptimise={runOptimise}
              onApply={onApplyPlan}
              onClose={() => setSelectedId(null)}
            />
          </div>
        )}
      </div>
    </section>
  )
}
