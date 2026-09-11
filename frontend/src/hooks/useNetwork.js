/**
 * The trade-lane network, fetched once and shared by every page that draws a
 * map.
 *
 * Registry, route geometry and emission control areas arrive together and
 * never change at runtime, so this memoises the derived shapes — lane
 * geometries in particular, which are rebuilt into SVG paths and would
 * otherwise be recomputed on every render of a page that animates at 60 fps.
 */
import { useMemo } from 'react'

import { buildGeometries, decoratePorts } from '../data/geography'
import { useFetch } from './useApi'
import api from '../lib/api'

const EMPTY = []

export function useNetwork() {
  const registry = useFetch((signal) => api.optimization.registry({ signal }), [])
  const eca = useFetch((signal) => api.regulatory.ecaZones({ signal }), [])

  const lanes = registry.data?.lanes ?? EMPTY
  const vessels = registry.data?.vessels ?? EMPTY

  const geometries = useMemo(() => buildGeometries(lanes), [lanes])
  const ports = useMemo(() => decoratePorts(registry.data?.ports ?? EMPTY), [registry.data])
  const chokepoints = registry.data?.chokepoints ?? EMPTY
  const lanesByName = useMemo(
    () => Object.fromEntries(lanes.map((lane) => [lane.name, lane])),
    [lanes],
  )

  return {
    registry: registry.data,
    lanes,
    vessels,
    lanesByName,
    geometries,
    ports,
    chokepoints,
    ecaZones: eca.data?.zones ?? EMPTY,
    ecaLanes: eca.data?.lanes ?? EMPTY,
    ecaDisclaimer: eca.data?.disclaimer,
    loading: registry.loading || eca.loading,
    error: registry.error || eca.error,
    refetch: registry.refetch,
  }
}

export default useNetwork
