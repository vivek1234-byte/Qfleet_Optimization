/**
 * A map with ships on it.
 *
 * Pulled out of the simulator page because the split-screen comparison needs
 * two of them side by side, driven by one clock, and duplicating the wiring
 * would guarantee the two panes drifted apart.
 */
import ShipLayer from './ShipLayer'
import WorldMap, { useMapViewport } from './WorldMap'
import { fuelColor } from '../lib/domain'
import { cx } from './ui'

export default function VoyageMap({
  viewport,
  network,
  ships,
  clockRef,
  running,
  timeScale,
  layers,
  selectedId,
  dimmedIds,
  onSelect,
  onTick,
  onSelectLane,
  activeLanes,
  activePorts,
  badge,
  badgeTone = 'neutral',
  legendFuels,
  className,
  children,
}) {
  return (
    <div className={cx('relative h-full w-full overflow-hidden', className)}>
      <WorldMap
        viewport={viewport}
        lanes={network.lanes}
        geometries={network.geometries}
        ports={network.ports}
        chokepoints={network.chokepoints}
        ecaZones={network.ecaZones}
        activeLanes={activeLanes}
        activePorts={activePorts}
        showPortLabels={layers.portLabels}
        showChokepoints={layers.chokepoints}
        showGraticule={layers.graticule}
        showEca={layers.eca}
        laneColorBy={layers.weather ? 'weather' : 'uniform'}
        paused={!running}
        onSelectLane={onSelectLane}
      >
        <ShipLayer
          ships={ships}
          geometries={network.geometries}
          clockRef={clockRef}
          running={running}
          timeScale={timeScale}
          selectedId={selectedId}
          dimmedIds={dimmedIds}
          showTrails={layers.trails}
          showNames={layers.names}
          onSelect={onSelect}
          onTick={onTick}
        />
      </WorldMap>

      {badge && (
        <div
          className={cx(
            'absolute left-3 top-3 rounded-md px-2.5 py-1 text-xs font-semibold',
            badgeTone === 'eco'
              ? 'bg-eco-600/90 text-white'
              : badgeTone === 'warning'
                ? 'bg-amber-600/90 text-white'
                : 'bg-black/70 text-slate-100',
          )}
        >
          {badge}
        </div>
      )}

      {legendFuels?.length > 0 && (
        <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-black/70 px-2.5 py-1.5">
          {legendFuels.map((fuel) => (
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
      )}

      {children}
    </div>
  )
}

export { useMapViewport }
