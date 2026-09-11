/**
 * Data-fetching hooks.
 *
 * Every page previously handled loading/error/abort by hand (or, in the case of
 * the optimizer, not at all — it used a setTimeout and made no request). These
 * two hooks give every screen the same lifecycle, including cancelling an
 * in-flight request when the component unmounts or the user fires another one.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

/**
 * Run an async function on demand.
 *
 * @param {(signal: AbortSignal, ...args: any[]) => Promise<any>} fn
 */
export function useAsync(fn) {
  const [state, setState] = useState({ data: null, error: null, loading: false })
  const controllerRef = useRef(null)
  const mountedRef = useRef(true)
  // Keep the latest callback without making `run` depend on it, so a caller
  // can define the function inline without re-creating `run` every render.
  // Assigned in a layout effect rather than during render, which keeps the
  // render pass side-effect free.
  const fnRef = useRef(fn)
  useLayoutEffect(() => {
    fnRef.current = fn
  })

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      controllerRef.current?.abort()
    }
  }, [])

  const run = useCallback(async (...args) => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    setState((prev) => ({ ...prev, loading: true, error: null }))
    try {
      const data = await fnRef.current(controller.signal, ...args)
      if (!mountedRef.current || controller.signal.aborted) return undefined
      setState({ data, error: null, loading: false })
      return data
    } catch (error) {
      if (error?.cancelled || controller.signal.aborted || !mountedRef.current) return undefined
      setState({ data: null, error, loading: false })
      return undefined
    }
  }, [])

  const reset = useCallback(() => {
    controllerRef.current?.abort()
    setState({ data: null, error: null, loading: false })
  }, [])

  return { ...state, run, reset }
}

/**
 * Fetch once on mount (and whenever `deps` change), with a refetch handle.
 *
 * @param {(signal: AbortSignal) => Promise<any>} fn
 * @param {any[]} deps
 */
export function useFetch(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const [nonce, setNonce] = useState(0)
  const fnRef = useRef(fn)
  useLayoutEffect(() => {
    fnRef.current = fn
  })

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setState((prev) => ({ ...prev, loading: true, error: null }))

    fnRef
      .current(controller.signal)
      .then((data) => {
        if (active && !controller.signal.aborted) setState({ data, error: null, loading: false })
      })
      .catch((error) => {
        if (!active || error?.cancelled || controller.signal.aborted) return
        setState({ data: null, error, loading: false })
      })

    return () => {
      active = false
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  const refetch = useCallback(() => setNonce((n) => n + 1), [])
  return { ...state, refetch }
}

/** Poll a function on an interval. Used for the backend health indicator. */
export function usePolling(fn, intervalMs = 30_000) {
  const result = useFetch(fn, [])
  const { refetch } = result

  useEffect(() => {
    if (!intervalMs) return undefined
    const id = setInterval(refetch, intervalMs)
    return () => clearInterval(id)
  }, [refetch, intervalMs])

  return result
}
