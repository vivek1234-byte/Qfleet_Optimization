/**
 * The optimised plan, shared between pages.
 *
 * The optimizer produces a plan and the simulator sails it. Routing between
 * them must not lose it, and a React context would have to wrap the whole app
 * just to move one object, so this is a tiny external store read through
 * `useSyncExternalStore`.
 */
import { useSyncExternalStore } from 'react'

let state = { result: null, baseline: null, source: null, at: null }
const listeners = new Set()

function emit() {
  listeners.forEach((l) => l())
}

const subscribe = (listener) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

const getSnapshot = () => state

/** Store the outcome of an optimisation run. */
export function setActivePlan(result, source = 'optimizer') {
  state = { result, baseline: result?.baseline_objectives ?? null, source, at: Date.now() }
  emit()
}

export function clearActivePlan() {
  state = { result: null, baseline: null, source: null, at: null }
  emit()
}

export function useActivePlan() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

export default useActivePlan
