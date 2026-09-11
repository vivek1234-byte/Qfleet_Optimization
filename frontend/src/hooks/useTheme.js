/**
 * Light/dark theme, persisted per browser.
 *
 * Kept in its own module so the shell exports components only (fast refresh
 * bails out on a file that mixes components with hooks and constants).
 */
import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'qfleet-theme'

function readInitialTheme() {
  if (typeof window === 'undefined') return 'light'
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // Private browsing can throw on storage access; fall through to the
    // system preference rather than failing to render.
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function useTheme() {
  const [theme, setTheme] = useState(readInitialTheme)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try {
      window.localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      // Not fatal — the theme still applies for this session.
    }
  }, [theme])

  const toggleTheme = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), [])
  return [theme, toggleTheme]
}

export default useTheme
