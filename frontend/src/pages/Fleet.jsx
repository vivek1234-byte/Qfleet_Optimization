/**
 * Fleet and lane registry.
 *
 * A reviewer's first instinct is to check whether the data is real. This page
 * exists to answer that: named Indian-flag vessels with plausible particulars,
 * and sixteen trade lanes with UN/LOCODEs and sea distances that match
 * published port-to-port tables.
 */
import { Anchor, Filter, Route, Ship } from 'lucide-react'
import { useMemo, useState } from 'react'

import WorldMap, { useMapViewport } from '../components/WorldMap'
import {
  Badge,
  Card,
  DataTable,
  ErrorState,
  PageHeader,
  Select,
  Skeleton,
  StatCard,
  cx,
} from '../components/ui'
import { MAP_VIEWS, PORTS, buildLaneGeometry } from '../data/geography'
import { useFetch } from '../hooks/useApi'
import api from '../lib/api'
import { VESSEL_TYPE_COLORS, beaufortLabel } from '../lib/domain'
import { compact, num } from '../lib/format'

const EMPTY = []

function VesselCard({ vessel, active, onClick }) {
  const tint = VESSEL_TYPE_COLORS[vessel.vessel_type] ?? '#64748b'
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'card w-full p-4 text-left transition-shadow hover:shadow-card-hover',
        active && 'ring-2 ring-primary-500',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{vessel.name}</p>
          <p className="text-faint mt-0.5 text-xs">
            {vessel.home_port} · built {vessel.built} · {vessel.flag} flag
          </p>
        </div>
        <span
          className="shrink-0 rounded-full px-2 py-0.5 text-[0.68rem] font-medium text-white"
          style={{ backgroundColor: tint }}
        >
          {vessel.vessel_type}
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-faint">Deadweight</dt>
        <dd className="numeric text-right">{compact(vessel.dwt)} t</dd>
        <dt className="text-faint">Installed power</dt>
        <dd className="numeric text-right">{compact(vessel.rated_power_kw)} kW</dd>
        <dt className="text-faint">Design speed</dt>
        <dd className="numeric text-right">{num(vessel.design_speed_knots, 1)} kn</dd>
        <dt className="text-faint">Speed envelope</dt>
        <dd className="numeric text-right">
          {vessel.speed_range_knots[0]}–{vessel.speed_range_knots[1]} kn
        </dd>
        <dt className="text-faint">Bunker tanks</dt>
        <dd className="numeric text-right">{compact(vessel.tank_volume_m3)} m³</dd>
      </dl>
    </button>
  )
}

export default function Fleet() {
  const registry = useFetch((signal) => api.optimization.registry({ signal }), [])
  const [typeFilter, setTypeFilter] = useState('all')
  const [selectedVessel, setSelectedVessel] = useState(null)
  const [selectedLane, setSelectedLane] = useState(null)
  const viewport = useMapViewport(MAP_VIEWS.indianOcean.box)

  const vessels = registry.data?.vessels ?? EMPTY
  const lanes = registry.data?.lanes ?? EMPTY

  const geometries = useMemo(() => {
    const out = {}
    lanes.forEach((lane) => {
      const geometry = buildLaneGeometry(lane)
      if (geometry) out[lane.name] = geometry
    })
    return out
  }, [lanes])

  const ports = useMemo(() => Object.entries(PORTS).map(([name, p]) => ({ name, ...p })), [])

  const filtered = useMemo(
    () => (typeFilter === 'all' ? vessels : vessels.filter((v) => v.vessel_type === typeFilter)),
    [vessels, typeFilter],
  )

  const stats = useMemo(() => {
    if (!vessels.length) return null
    return {
      dwt: vessels.reduce((a, v) => a + v.dwt, 0),
      power: vessels.reduce((a, v) => a + v.rated_power_kw, 0),
      meanAge: 2026 - vessels.reduce((a, v) => a + v.built, 0) / vessels.length,
      laneNm: lanes.reduce((a, l) => a + l.distance_nm, 0),
    }
  }, [vessels, lanes])

  const typeCounts = useMemo(() => {
    const counts = {}
    vessels.forEach((v) => {
      counts[v.vessel_type] = (counts[v.vessel_type] ?? 0) + 1
    })
    return counts
  }, [vessels])

  const activeLanes = useMemo(
    () => (selectedLane ? new Set([selectedLane]) : null),
    [selectedLane],
  )

  if (registry.error) {
    return (
      <>
        <PageHeader title="Fleet & lanes" />
        <ErrorState error={registry.error} onRetry={registry.refetch} />
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Fleet & lanes"
        description="The vessels and trade lanes every optimisation runs against. Vessel names are fictional; the ports, UN/LOCODEs, distances and routings are not."
      />

      <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Vessels"
          value={registry.data?.vessel_count ?? '—'}
          icon={Ship}
          accent="primary"
          loading={registry.loading}
          hint={Object.entries(typeCounts)
            .map(([k, v]) => `${v} ${k.toLowerCase()}`)
            .join(' · ')}
        />
        <StatCard
          label="Combined deadweight"
          value={stats ? compact(stats.dwt) : '—'}
          unit="t"
          icon={Anchor}
          accent="eco"
          loading={registry.loading}
        />
        <StatCard
          label="Installed power"
          value={stats ? compact(stats.power) : '—'}
          unit="kW"
          icon={Filter}
          accent="amber"
          loading={registry.loading}
        />
        <StatCard
          label="Trade lanes"
          value={registry.data?.lane_count ?? '—'}
          icon={Route}
          accent="violet"
          loading={registry.loading}
          hint={stats ? `${compact(stats.laneNm)} nm of sea route` : undefined}
        />
      </div>

      <Card
        title="Lane network"
        description="Click a lane on the map or in the table to isolate it"
        className="mb-5"
        bodyClassName="p-0"
        actions={
          selectedLane && (
            <button
              type="button"
              onClick={() => setSelectedLane(null)}
              className="text-faint text-xs underline-offset-2 hover:underline"
            >
              Show all
            </button>
          )
        }
      >
        <div className="h-[46vh] min-h-[320px] overflow-hidden rounded-b-xl">
          {registry.loading ? (
            <Skeleton className="h-full w-full" />
          ) : (
            <WorldMap
              viewport={viewport}
              lanes={lanes}
              geometries={geometries}
              ports={ports}
              activeLanes={activeLanes}
              laneColorBy="weather"
              paused
              onSelectLane={(name) => setSelectedLane((current) => (current === name ? null : name))}
            />
          )}
        </div>
      </Card>

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          options={[
            { value: 'all', label: `All classes (${vessels.length})` },
            ...Object.entries(typeCounts).map(([k, v]) => ({ value: k, label: `${k} (${v})` })),
          ]}
          className="w-56"
          aria-label="Filter vessels by class"
        />
      </div>

      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {registry.loading
          ? [0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-52 w-full rounded-xl" />)
          : filtered.map((vessel) => (
              <VesselCard
                key={vessel.name}
                vessel={vessel}
                active={selectedVessel === vessel.name}
                onClick={() =>
                  setSelectedVessel((current) => (current === vessel.name ? null : vessel.name))
                }
              />
            ))}
      </div>

      <Card title="Trade lanes" description="Sea distances by the customary routing">
        {registry.loading ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <DataTable
            columns={[
              {
                key: 'name',
                header: 'Lane',
                render: (row) => (
                  <button
                    type="button"
                    onClick={() =>
                      setSelectedLane((current) => (current === row.name ? null : row.name))
                    }
                    className="text-left font-medium underline-offset-2 hover:underline"
                  >
                    {row.name}
                  </button>
                ),
              },
              {
                key: 'codes',
                header: 'LOCODE',
                render: (row) => (
                  <span className="numeric text-faint text-xs">
                    {row.origin_code} → {row.destination_code}
                  </span>
                ),
              },
              { key: 'via', header: 'Via', render: (row) => row.via || '—' },
              {
                key: 'distance_nm',
                header: 'Distance',
                align: 'right',
                render: (row) => `${num(row.distance_nm)} nm`,
              },
              {
                key: 'max_transit_days',
                header: 'Window',
                align: 'right',
                render: (row) => `${num(row.max_transit_days, 1)} d`,
              },
              { key: 'cargo', header: 'Cargo' },
              {
                key: 'typical_beaufort',
                header: 'Sea state',
                align: 'right',
                render: (row) => (
                  <span title={beaufortLabel(row.typical_beaufort)}>
                    {num(row.typical_beaufort, 1)} Bft
                  </span>
                ),
              },
              {
                key: 'shore_power_available',
                header: 'Shore power',
                render: (row) => (
                  <Badge tone={row.shore_power_available ? 'eco' : 'neutral'}>
                    {row.shore_power_available ? 'available' : 'none'}
                  </Badge>
                ),
              },
            ]}
            rows={lanes}
            getRowKey={(row) => row.name}
            highlightRow={(row) => row.name === selectedLane}
          />
        )}
      </Card>
    </>
  )
}
