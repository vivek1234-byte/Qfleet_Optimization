/**
 * Chart theming.
 *
 * Recharts renders axes, grids and tooltips with fixed colours by default,
 * which made the original dashboard chart unreadable against a dark surface and
 * inconsistent between pages. These wrappers read the same CSS variables as the
 * rest of the UI, so every chart follows the theme.
 */
import { useEffect, useState } from 'react'
import { CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

/** Categorical series palette — distinguishable in both themes and colour-safe. */
export const SERIES_COLORS = [
  '#06a3ee', // primary
  '#15af73', // eco
  '#f59e0b', // amber
  '#8b5cf6', // violet
  '#ef4444', // rose
  '#14b8a6', // teal
]

export const ALGORITHM_COLORS = {
  qpso: '#06a3ee',
  qga: '#8b5cf6',
  pso: '#f59e0b',
  nsga2: '#15af73',
}

export const colorForSeries = (name, index = 0) =>
  ALGORITHM_COLORS[name] ?? SERIES_COLORS[index % SERIES_COLORS.length]

/** Reads a CSS custom property and re-reads it when the theme class changes. */
function useCssVar(name, fallback) {
  const read = () => {
    if (typeof window === 'undefined') return fallback
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return value ? `rgb(${value})` : fallback
  }
  const [value, setValue] = useState(read)

  useEffect(() => {
    const observer = new MutationObserver(() => setValue(read()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name])

  return value
}

export function useChartTheme() {
  return {
    grid: useCssVar('--chart-grid', '#e2e8f0'),
    axis: useCssVar('--chart-axis', '#94a3b8'),
    surface: useCssVar('--surface-card', '#ffffff'),
    border: useCssVar('--border-subtle', '#e2e8f0'),
    text: useCssVar('--text-primary', '#0f172a'),
  }
}

export function ChartFrame({ height = 300, children }) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  )
}

export function ThemedGrid({ vertical = false }) {
  const { grid } = useChartTheme()
  return <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={vertical} />
}

export function ThemedXAxis(props) {
  const { axis } = useChartTheme()
  return (
    <XAxis
      stroke={axis}
      tick={{ fill: axis, fontSize: 12 }}
      tickLine={false}
      axisLine={{ stroke: axis, opacity: 0.3 }}
      {...props}
    />
  )
}

export function ThemedYAxis(props) {
  const { axis } = useChartTheme()
  return (
    <YAxis
      stroke={axis}
      tick={{ fill: axis, fontSize: 12 }}
      tickLine={false}
      axisLine={false}
      width={64}
      {...props}
    />
  )
}

export function ThemedTooltip(props) {
  const { surface, border, text } = useChartTheme()
  return (
    <Tooltip
      cursor={{ stroke: border, strokeWidth: 1 }}
      contentStyle={{
        background: surface,
        border: `1px solid ${border}`,
        borderRadius: 10,
        color: text,
        fontSize: 12,
        boxShadow: '0 12px 32px -8px rgb(16 24 40 / 0.18)',
      }}
      labelStyle={{ color: text, fontWeight: 600, marginBottom: 4 }}
      itemStyle={{ color: text }}
      {...props}
    />
  )
}

export function ThemedLegend(props) {
  const { axis } = useChartTheme()
  return (
    <Legend
      wrapperStyle={{ fontSize: 12, color: axis, paddingTop: 8 }}
      iconType="circle"
      iconSize={8}
      {...props}
    />
  )
}
