/**
 * Maritime Network Intelligence — the dashboard's network card.
 *
 * A map with a deployment plan behind it. Every number on this card comes
 * from `lib/networkIntel.js`, which derives them from the registry and from
 * the plan the optimiser produced; see that file for what is and is not
 * modelled. The rule this card follows is that a figure with no source does
 * not appear — the port panel says "not modelled" where a maritime operations
 * centre would show arrivals and berth turnaround, because this project has
 * no schedule feed and a plausible-looking number would be a lie with a
 * decimal point on it.
 *
 * Two states. With no optimisation run, the card shows the **baseline**
 * deployment — real, deterministic, straight from `/api/optimization/fleet`.
 * Run the optimiser and the same card re-renders against the optimised plan,
 * and the per-lane deltas become real comparisons rather than blanks. That
 * transition is the point of the section: it connects the map to the solver.
 */
import {
  Activity,
  Anchor,
  ChevronDown,
  Fuel as FuelIcon,
  Gauge,
  Leaf,
  Radar,
  Route as RouteIcon,
  Ship,
  TriangleAlert,
  Waves,
  X,
  Zap,
} from 'lucide-react'
import { memo, useMemo, useState } from 'react'

import WorldMap, { useMapViewport } from '../WorldMap'
import { FlowLayer, LANE_STATE_STROKE, VesselLayer } from './NetworkMapLayers'
import { Badge, Button, Card, Skeleton, cx } from '../ui'
import { MAP_VIEWS } from '../../data/geography'
import { fuelColor } from '../../lib/domain'
import { compact, num } from '../../lib/format'
import { UNAVAILABLE, buildNetworkIntel } from '../../lib/networkIntel'

const EMPTY = []

const LAYER_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'vessels', label: 'Vessels' },
  { id: 'ports', label: 'Ports' },
  { id: 'lanes', label: 'Trade lanes' },
]

/**
 * Four ways of reading the same plan. Each one re-weights what the map
 * emphasises; none of them fetches anything or changes the underlying data.
 */
const VIEWS = [
  { id: 'network', label: 'Network', hint: 'Lanes, ports and the assigned fleet' },
  { id: 'emissions', label: 'Emissions', hint: 'Lanes carrying the most CO₂' },
  { id: 'fuel', label: 'Fuel', hint: 'Lanes burning most per 1,000 nm' },
  { id: 'optimization', label: 'Optimisation', hint: 'Lanes the solver improved' },
]

const TONE_ICON = { eco: Leaf, warning: TriangleAlert, amber: FuelIcon, info: Zap }
const TONE_CLASS = {
  eco: 'text-eco-500',
  warning: 'text-amber-500',
  amber: 'text-orange-400',
  info: 'text-primary-400',
}

/* -------------------------------------------------------------------------- */
/* Small pieces                                                                */
/* -------------------------------------------------------------------------- */
function Kpi({ label, value, unit, hint }) {
  return (
    <div
      className="min-w-0 flex-1 px-4 py-3"
      style={{ borderLeft: '1px solid rgb(var(--border-subtle))' }}
    >
      <p className="numeric text-xl font-semibold tracking-tight">
        {value}
        {unit && <span className="text-faint ml-1 text-xs font-normal">{unit}</span>}
      </p>
      <p className="text-faint mt-0.5 truncate text-[0.7rem] uppercase tracking-wide" title={hint}>
        {label}
      </p>
    </div>
  )
}

function Pill({ active, children, ...props }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={cx(
        'shrink-0 whitespace-nowrap rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-150',
        active
          ? 'bg-primary-600 text-white'
          : 'text-[rgb(var(--text-secondary))] hover:bg-[rgb(var(--surface-sunken))]',
      )}
      {...props}
    >
      {children}
    </button>
  )
}

function Meter({ label, value, detail, unavailable }) {
  const pctValue = value === null || value === undefined ? null : Math.round(value * 100)
  const tone =
    pctValue === null ? 'bg-slate-600' : pctValue >= 90 ? 'bg-eco-500' : pctValue >= 70 ? 'bg-primary-500' : 'bg-amber-500'
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="truncate">{label}</span>
        <span className="numeric text-faint shrink-0">
          {pctValue === null ? '—' : `${pctValue}%`}
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[rgb(var(--surface-sunken))]">
        <div
          className={cx('h-full rounded-full transition-all duration-300', tone)}
          style={{ width: `${pctValue ?? 0}%` }}
        />
      </div>
      <p className="text-faint mt-1 text-[0.68rem] leading-snug">{unavailable ?? detail}</p>
    </div>
  )
}

function Field({ label, children, mono = true }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-faint shrink-0 text-[0.7rem] uppercase tracking-wide">{label}</span>
      <span className={cx('min-w-0 truncate text-right text-xs', mono && 'numeric')}>{children}</span>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Detail panels                                                               */
/* -------------------------------------------------------------------------- */
function DetailPanel({ title, subtitle, onClose, children, tone = 'neutral' }) {
  return (
    <div
      className="animate-fade-in w-full rounded-lg border p-3 shadow-pop backdrop-blur-sm lg:absolute lg:right-3 lg:top-3 lg:z-10 lg:w-[17.5rem]"
      style={{
        backgroundColor: 'rgb(var(--surface-card) / 0.96)',
        borderColor: 'rgb(var(--border-strong))',
      }}
      role="region"
      aria-label={title}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{title}</p>
          {subtitle && <p className="text-faint truncate text-xs">{subtitle}</p>}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close panel"
          className="text-faint shrink-0 rounded p-0.5 transition-colors hover:text-[rgb(var(--text-primary))]"
        >
          <X size={14} />
        </button>
      </div>
      {tone !== 'neutral' && (
        <div className="mb-2">
          <Badge tone={tone === 'eco' ? 'eco' : tone === 'warning' ? 'warning' : 'neutral'}>
            {tone === 'eco' ? 'Optimised' : tone === 'warning' ? 'Schedule pressure' : 'Active'}
          </Badge>
        </div>
      )}
      <div style={{ borderTop: '1px solid rgb(var(--border-subtle))' }} className="pt-1.5">
        {children}
      </div>
    </div>
  )
}

function LanePanel({ lane, hasPlan, onClose }) {
  return (
    <DetailPanel
      title={`${lane.origin} → ${lane.destination}`}
      subtitle={lane.via ? `via ${lane.via} · ${lane.cargo}` : lane.cargo}
      tone={lane.state === 'optimised' ? 'eco' : lane.state === 'pressure' ? 'warning' : 'neutral'}
      onClose={onClose}
    >
      <Field label="Distance">{num(lane.distanceNm, 0)} nm</Field>
      <Field label="Vessels">{lane.vessels}</Field>
      <Field label="Average speed">{lane.avgSpeed ? `${lane.avgSpeed} kn` : '—'}</Field>
      <Field label="Voyage">{lane.voyageDays ? `${lane.voyageDays} d` : '—'}</Field>
      <Field label="Transit window">{lane.maxTransitDays} d</Field>
      <Field label="Fuel">{num(lane.fuelTons, 0)} t</Field>
      <Field label="CO₂">{num(lane.co2Tons, 0)} t</Field>
      <Field label="Intensity">{lane.fuelPerKnm} t / 1,000 nm</Field>
      <Field label="Capacity used">
        {lane.utilisation === null
          ? '—'
          : `${Math.round(lane.utilisation * 100)}% of ${compact(lane.capacityTons)} t`}
      </Field>
      {lane.ecaFraction > 0 && (
        <Field label="In ECA">{Math.round(lane.ecaFraction * 100)}%</Field>
      )}
      <Field label="Sea state">Beaufort {lane.beaufort}</Field>
      <div className="mt-1.5 pt-1.5" style={{ borderTop: '1px solid rgb(var(--border-subtle))' }}>
        {hasPlan ? (
          <>
            <Field label="Fuel vs baseline">
              <span className={lane.fuelDeltaPct < 0 ? 'text-eco-500' : 'text-faint'}>
                {lane.fuelDeltaPct === null ? '—' : `${lane.fuelDeltaPct > 0 ? '+' : ''}${lane.fuelDeltaPct}%`}
              </span>
            </Field>
            <Field label="CO₂ vs baseline">
              <span className={lane.co2DeltaPct < 0 ? 'text-eco-500' : 'text-faint'}>
                {lane.co2DeltaPct === null ? '—' : `${lane.co2DeltaPct > 0 ? '+' : ''}${lane.co2DeltaPct}%`}
              </span>
            </Field>
          </>
        ) : (
          <p className="text-faint text-[0.68rem] leading-snug">
            Run an optimisation to see how much fuel and CO₂ this lane can give up.
          </p>
        )}
      </div>
    </DetailPanel>
  )
}

function PortPanel({ port, onClose }) {
  return (
    <DetailPanel title={port.name} subtitle={port.code ?? 'Port'} onClose={onClose}>
      <Field label="Trade lanes">{port.laneCount}</Field>
      <Field label="Planned calls">{port.vessels}</Field>
      <Field label="Bunker demand">{num(port.fuelTons, 0)} t</Field>
      <Field label="CO₂ on its lanes">{num(port.co2Tons, 0)} t</Field>
      <Field label="Shore power">
        {port.shorePowerLanes > 0 ? `${port.shorePowerLanes} lane(s)` : 'Not available'}
      </Field>
      {/* Said plainly rather than filled with a convincing number. */}
      <div className="mt-2 pt-1.5" style={{ borderTop: '1px solid rgb(var(--border-subtle))' }}>
        <p className="text-faint text-[0.68rem] leading-snug">
          Arrivals, departures, berth turnaround and congestion are <strong>not modelled</strong> —
          the platform has no schedule or AIS feed. {UNAVAILABLE.turnaround}.
        </p>
      </div>
    </DetailPanel>
  )
}

function VesselPanel({ vessel, onClose }) {
  return (
    <DetailPanel title={vessel.name} subtitle={vessel.type} onClose={onClose}>
      <Field label="Route" mono={false}>
        {vessel.route}
      </Field>
      <Field label="Speed">{vessel.speed} kn</Field>
      <Field label="Fuel" mono={false}>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: fuelColor(vessel.fuel) }}
            aria-hidden
          />
          {vessel.fuel}
        </span>
      </Field>
      <Field label="Distance">{num(vessel.distanceNm, 0)} nm</Field>
      <Field label="Voyage">{vessel.voyageDays} d</Field>
      <Field label="Fuel burn">{num(vessel.fuelTons, 1)} t</Field>
      <Field label="CO₂">{num(vessel.co2Tons, 1)} t</Field>
      {vessel.ciiRating && <Field label="CII rating">{vessel.ciiRating}</Field>}
      {vessel.ecaShare > 0 && (
        <Field label="ECA switch">{Math.round(vessel.ecaShare * 100)}% of voyage</Field>
      )}
      <Field label="Status" mono={false}>
        {vessel.status}
      </Field>
    </DetailPanel>
  )
}

/* -------------------------------------------------------------------------- */
/* Legend                                                                      */
/* -------------------------------------------------------------------------- */
const Legend = memo(function Legend() {
  const line = (color) => (
    <span
      className="inline-block h-0.5 w-4 shrink-0 rounded-full"
      style={{ backgroundColor: color }}
      aria-hidden
    />
  )
  return (
    <div
      className="pointer-events-none absolute bottom-2.5 left-2.5 hidden gap-x-3 gap-y-1 rounded-md px-2.5 py-1.5 sm:flex sm:flex-wrap sm:max-w-[22rem]"
      style={{ backgroundColor: 'rgb(4 18 31 / 0.82)' }}
    >
      {[
        ['Vessel', <span key="v" className="inline-block h-2 w-2 shrink-0 rounded-full bg-slate-200" />],
        ['Port', <span key="p" className="inline-block h-2 w-2 shrink-0 rounded-full bg-[#e2f4ff]" />],
        ['Active', line(LANE_STATE_STROKE.normal)],
        ['Optimised', line(LANE_STATE_STROKE.optimised)],
        ['Schedule pressure', line(LANE_STATE_STROKE.pressure)],
        ['Fuel intensive', line(LANE_STATE_STROKE.intensive)],
      ].map(([label, mark]) => (
        <span key={label} className="flex items-center gap-1.5 text-[0.66rem] text-slate-200">
          {mark}
          {label}
        </span>
      ))}
    </div>
  )
})

/* -------------------------------------------------------------------------- */
/* Section                                                                     */
/* -------------------------------------------------------------------------- */
export default function NetworkSection({ network, baseline, plan, loading, onOpenSimulator }) {
  const viewport = useMapViewport(MAP_VIEWS.indianOcean.box)

  const [layer, setLayer] = useState('all')
  const [fuel, setFuel] = useState('all')
  const [view, setView] = useState('network')
  const [liveFlow, setLiveFlow] = useState(true)
  const [selection, setSelection] = useState(null) // {kind, id}
  const [hovered, setHovered] = useState(null)
  const [insightsOpen, setInsightsOpen] = useState(false)

  // Derived together on purpose: `updatedAt` is "when the data behind this
  // card last changed", so it belongs to the same memo as the derivation. A
  // separate effect would set state during render for no reason, and a
  // ticking clock would advance while nothing moved — theatre, not status.
  const { intel, updatedAt } = useMemo(
    () => ({
      intel: buildNetworkIntel({ plan, baseline, lanes: network.lanes, ports: network.ports }),
      updatedAt: new Date(),
    }),
    [plan, baseline, network.lanes, network.ports],
  )


  const fuelsPresent = useMemo(
    () => [...new Set(intel.vessels.map((v) => v.fuel))].sort(),
    [intel.vessels],
  )

  const visibleVessels = useMemo(() => {
    if (layer === 'ports' || layer === 'lanes') return EMPTY
    if (fuel === 'all') return intel.vessels
    return intel.vessels.filter((v) => v.fuel === fuel)
  }, [intel.vessels, layer, fuel])

  const laneStates = useMemo(
    () => Object.fromEntries(intel.lanes.map((lane) => [lane.name, lane.state])),
    [intel.lanes],
  )

  /**
   * Which lanes the current view emphasises. Each is a real ordering of the
   * plan's own numbers, not a separate dataset.
   */
  const emphasis = useMemo(() => {
    const carrying = intel.lanes.filter((l) => l.vessels > 0)
    if (view === 'emissions') {
      return [...carrying].sort((a, b) => b.co2Tons - a.co2Tons).slice(0, 6).map((l) => l.name)
    }
    if (view === 'fuel') {
      return [...carrying].sort((a, b) => b.fuelPerKnm - a.fuelPerKnm).slice(0, 6).map((l) => l.name)
    }
    if (view === 'optimization') {
      const improved = carrying.filter((l) => l.state === 'optimised' || l.state === 'intensive')
      return improved.map((l) => l.name)
    }
    return EMPTY
  }, [intel.lanes, view])

  const activeLanes = useMemo(() => {
    if (layer === 'vessels' || layer === 'ports') return new Set()
    if (emphasis.length) return new Set(emphasis)
    return undefined
  }, [layer, emphasis])

  const topLanes = useMemo(
    () =>
      [...intel.lanes]
        .filter((lane) => lane.vessels > 0)
        .sort((a, b) => b.vessels - a.vessels || b.distanceNm - a.distanceNm)
        .slice(0, 5),
    [intel.lanes],
  )

  const selectedLane = selection?.kind === 'lane' && intel.lanes.find((l) => l.name === selection.id)
  const selectedPort = selection?.kind === 'port' && intel.portStats[selection.id]
  const selectedVessel = selection?.kind === 'vessel' && intel.vessels.find((v) => v.id === selection.id)

  const shownInsights = insightsOpen ? intel.insights : intel.insights.slice(0, 3)

  return (
    <Card
      title="Maritime Network Intelligence"
      description="Real-time overview of vessels, trade lanes, ports and network efficiency"
      bodyClassName="p-0"
      actions={
        <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1.5">
          <span className="flex items-center gap-1.5 text-[0.7rem]">
            <span
              className={cx(
                'h-1.5 w-1.5 rounded-full',
                intel.ready ? 'bg-eco-500' : 'bg-amber-500',
              )}
              aria-hidden
            />
            <span className="text-[rgb(var(--text-secondary))]">
              {intel.ready ? 'Network operational' : 'Awaiting plan'}
            </span>
            <span className="text-faint numeric">
              · {updatedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          </span>
          <Button size="sm" variant="secondary" icon={Radar} onClick={onOpenSimulator}>
            Open live simulator
          </Button>
        </div>
      }
    >
      {/* ---- KPI strip ---------------------------------------------------- */}
      <div
        className="flex flex-wrap"
        style={{ borderBottom: '1px solid rgb(var(--border-subtle))' }}
      >
        <Kpi
          label="Active vessels"
          value={loading ? '—' : intel.kpis.vessels}
          hint="Vessels carrying an assignment in the current plan"
        />
        <Kpi
          label="Trade lanes"
          value={loading ? '—' : `${intel.kpis.lanes}/${intel.kpis.totalLanes}`}
          hint="Lanes with at least one vessel assigned, of the registry total"
        />
        <Kpi
          label="Ports connected"
          value={loading ? '—' : intel.kpis.ports}
          hint="Distinct ports touched by the registry's trade lanes"
        />
        <Kpi
          label="Demand coverage"
          value={
            loading || intel.kpis.coverage === null
              ? '—'
              : `${Math.round(intel.kpis.coverage * 100)}`
          }
          unit="%"
          hint="Share of active lanes whose assigned deadweight meets their demand"
        />
      </div>

      {/* ---- filters ------------------------------------------------------ */}
      <div
        className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2"
        style={{ borderBottom: '1px solid rgb(var(--border-subtle))' }}
      >
        <div className="flex min-w-0 items-center gap-1 overflow-x-auto" role="group" aria-label="Map layers">
          {LAYER_FILTERS.map((item) => (
            <Pill key={item.id} active={layer === item.id} onClick={() => setLayer(item.id)}>
              {item.label}
            </Pill>
          ))}
        </div>

        <label className="flex items-center gap-1.5 text-[0.7rem]">
          <span className="text-faint uppercase tracking-wide">Fuel</span>
          <select
            value={fuel}
            onChange={(event) => setFuel(event.target.value)}
            className="rounded-md border px-1.5 py-1 text-xs"
            style={{
              backgroundColor: 'rgb(var(--surface-sunken))',
              borderColor: 'rgb(var(--border-subtle))',
            }}
            aria-label="Filter vessels by fuel"
          >
            <option value="all">All</option>
            {fuelsPresent.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <div className="flex min-w-0 items-center gap-1 overflow-x-auto" role="group" aria-label="Map view">
          {VIEWS.map((item) => (
            <Pill
              key={item.id}
              active={view === item.id}
              onClick={() => setView(item.id)}
              title={item.hint}
            >
              {item.label}
            </Pill>
          ))}
        </div>

        <button
          type="button"
          onClick={() => setLiveFlow((on) => !on)}
          aria-pressed={liveFlow}
          className={cx(
            'ml-auto flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[0.7rem] font-medium transition-colors duration-150',
            liveFlow
              ? 'text-eco-500 hover:bg-[rgb(var(--surface-sunken))]'
              : 'text-faint hover:bg-[rgb(var(--surface-sunken))]',
          )}
        >
          <span
            className={cx('h-1.5 w-1.5 rounded-full', liveFlow ? 'bg-eco-500' : 'bg-slate-500')}
            aria-hidden
          />
          Live flow
        </button>
      </div>

      {/* ---- map ---------------------------------------------------------- */}
      <div className="relative">
        <div className="h-[22rem] overflow-hidden sm:h-[26rem]">
          {loading ? (
            <Skeleton className="h-full w-full" />
          ) : (
            <WorldMap
              viewport={viewport}
              lanes={layer === 'vessels' || layer === 'ports' ? EMPTY : network.lanes}
              geometries={network.geometries}
              ports={layer === 'vessels' || layer === 'lanes' ? EMPTY : network.ports}
              chokepoints={EMPTY}
              showPortLabels={layer !== 'vessels'}
              showChokepoints={false}
              showGraticule
              activeLanes={activeLanes}
              laneStates={laneStates}
              paused={!liveFlow}
              onSelectLane={(name) => setSelection({ kind: 'lane', id: name })}
              onSelectPort={(name) => setSelection({ kind: 'port', id: name })}
            >
              {liveFlow && (
                <FlowLayer
                  lanes={layer === 'vessels' || layer === 'ports' ? EMPTY : network.lanes}
                  geometries={network.geometries}
                  laneStates={laneStates}
                  running={liveFlow}
                  emphasis={emphasis}
                />
              )}
              <VesselLayer
                vessels={visibleVessels}
                geometries={network.geometries}
                selectedId={selection?.kind === 'vessel' ? selection.id : null}
                onSelect={(vessel) => setSelection({ kind: 'vessel', id: vessel.id })}
                onHover={setHovered}
              />
            </WorldMap>
          )}
          <Legend />

          {/* Hover readout. Deliberately one line — the detail lives in the
              panel, and a map covered in tooltips is unreadable. */}
          {hovered && !selection && (
            <div
              className="pointer-events-none absolute left-2.5 top-2.5 rounded-md px-2.5 py-1.5 text-[0.7rem] text-slate-100"
              style={{ backgroundColor: 'rgb(4 18 31 / 0.9)' }}
            >
              <span className="font-semibold">{hovered.name}</span>
              <span className="text-slate-400">
                {' '}
                · {hovered.type} · {hovered.speed} kn · {hovered.fuel}
              </span>
            </div>
          )}
        </div>

        {/* Panels sit over the map on wide screens and stack under it on
            narrow ones — an absolutely positioned card on a phone covers the
            thing it is describing. */}
        {(selectedLane || selectedPort || selectedVessel) && (
          <div className="px-3 pb-3 lg:p-0">
            {selectedLane && (
              <LanePanel
                lane={selectedLane}
                hasPlan={Boolean(plan)}
                onClose={() => setSelection(null)}
              />
            )}
            {selectedPort && <PortPanel port={selectedPort} onClose={() => setSelection(null)} />}
            {selectedVessel && (
              <VesselPanel vessel={selectedVessel} onClose={() => setSelection(null)} />
            )}
          </div>
        )}
      </div>

      {/* ---- ranking, health, insights ------------------------------------ */}
      <div
        className="grid gap-px"
        style={{ borderTop: '1px solid rgb(var(--border-subtle))', gridTemplateColumns: '1fr' }}
      >
        <div className="grid lg:grid-cols-[1.4fr_1fr]">
          {/* Top trade lanes */}
          <div className="p-4" style={{ borderRight: '1px solid rgb(var(--border-subtle))' }}>
            <div className="mb-2.5 flex items-center gap-2">
              <RouteIcon size={14} className="text-faint" aria-hidden />
              <h3 className="text-xs font-semibold uppercase tracking-wide">Top trade lanes</h3>
              <span className="text-faint text-[0.68rem]">by vessels assigned</span>
            </div>
            {loading ? (
              <Skeleton className="h-32 w-full" />
            ) : topLanes.length === 0 ? (
              <p className="text-faint py-6 text-center text-xs">No lane carries a vessel yet.</p>
            ) : (
              <ol className="space-y-1">
                {topLanes.map((lane, index) => (
                  <li key={lane.name}>
                    <button
                      type="button"
                      onClick={() => setSelection({ kind: 'lane', id: lane.name })}
                      className="w-full rounded-md px-2 py-1.5 text-left transition-colors duration-150 hover:bg-[rgb(var(--surface-sunken))]"
                    >
                      <div className="flex items-baseline gap-2">
                        <span className="numeric text-faint w-4 shrink-0 text-xs">{index + 1}</span>
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">
                          {lane.origin} → {lane.destination}
                        </span>
                        {lane.state !== 'normal' && (
                          <span
                            className="h-1.5 w-1.5 shrink-0 rounded-full"
                            style={{ backgroundColor: LANE_STATE_STROKE[lane.state] }}
                            title={lane.state}
                            aria-hidden
                          />
                        )}
                      </div>
                      <p className="numeric text-faint ml-6 truncate text-[0.7rem]">
                        {lane.vessels} vessel{lane.vessels === 1 ? '' : 's'} ·{' '}
                        {num(lane.distanceNm, 0)} nm ·{' '}
                        {lane.utilisation === null
                          ? '— coverage'
                          : `${Math.round(lane.utilisation * 100)}% of capacity`}
                        {lane.co2DeltaPct !== null && (
                          <span className={lane.co2DeltaPct < 0 ? 'text-eco-500' : ''}>
                            {' '}
                            · {lane.co2DeltaPct > 0 ? '+' : ''}
                            {lane.co2DeltaPct}% CO₂
                          </span>
                        )}
                      </p>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </div>

          {/* Health + insights */}
          <div className="space-y-4 p-4">
            <div>
              <div className="mb-2.5 flex items-center gap-2">
                <Gauge size={14} className="text-faint" aria-hidden />
                <h3 className="text-xs font-semibold uppercase tracking-wide">Network health</h3>
              </div>
              {loading ? (
                <Skeleton className="h-24 w-full" />
              ) : (
                <div className="space-y-2.5">
                  {intel.health.map((row) => (
                    <Meter key={row.label} {...row} />
                  ))}
                </div>
              )}
            </div>

            <div style={{ borderTop: '1px solid rgb(var(--border-subtle))' }} className="pt-3">
              <div className="mb-2 flex items-center gap-2">
                <Activity size={14} className="text-faint" aria-hidden />
                <h3 className="text-xs font-semibold uppercase tracking-wide">
                  Network intelligence
                </h3>
              </div>
              <ul className="space-y-1.5">
                {shownInsights.map((insight) => {
                  const Icon = TONE_ICON[insight.tone] ?? Zap
                  return (
                    <li key={insight.key} className="flex items-start gap-2 text-[0.72rem] leading-snug">
                      <Icon
                        size={13}
                        className={cx('mt-0.5 shrink-0', TONE_CLASS[insight.tone])}
                        aria-hidden
                      />
                      <span className="text-[rgb(var(--text-secondary))]">{insight.text}</span>
                    </li>
                  )
                })}
              </ul>
              {intel.insights.length > 3 && (
                <button
                  type="button"
                  onClick={() => setInsightsOpen((open) => !open)}
                  className="text-faint mt-2 flex items-center gap-1 text-[0.7rem] transition-colors duration-150 hover:text-[rgb(var(--text-primary))]"
                >
                  <ChevronDown
                    size={12}
                    className={cx('transition-transform duration-200', insightsOpen && 'rotate-180')}
                    aria-hidden
                  />
                  {insightsOpen ? 'Show fewer' : `${intel.insights.length - 3} more insight(s)`}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ---- provenance ---------------------------------------------------- */}
      <div
        className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-[0.68rem]"
        style={{ borderTop: '1px solid rgb(var(--border-subtle))' }}
      >
        <span className="text-faint flex items-center gap-1.5">
          <Ship size={11} aria-hidden />
          {intel.source === 'optimised'
            ? 'Figures from the active optimised plan'
            : 'Figures from the baseline deployment'}
        </span>
        {intel.objectives && (
          <>
            <span className="text-faint numeric flex items-center gap-1.5">
              <FuelIcon size={11} aria-hidden />
              {compact(intel.objectives.fuel_consumption_tons)} t fuel
            </span>
            <span className="text-faint numeric flex items-center gap-1.5">
              <Leaf size={11} aria-hidden />
              {compact(intel.objectives.co2_emissions_tons)} t CO₂
            </span>
          </>
        )}
        {intel.averageSpeed && (
          <span className="text-faint numeric flex items-center gap-1.5">
            <Waves size={11} aria-hidden />
            {intel.averageSpeed} kn average
          </span>
        )}
        <span className="text-faint ml-auto flex items-center gap-1.5">
          <Anchor size={11} aria-hidden />
          Port call and congestion data not modelled
        </span>
      </div>
    </Card>
  )
}
