/**
 * The sea-state warning dot, and the panel behind it.
 *
 * Lives in the header, so the warning follows the operator onto every screen
 * rather than waiting on the one page they might not open. The dot is red
 * when any lane is high-impact, amber below that, and absent entirely when
 * the water is behaving — a permanent badge is wallpaper, and an operator
 * stops reading wallpaper.
 *
 * Every figure comes from `/api/regulatory/alerts`, which derives them from
 * each lane's registry Beaufort and the monthly basin climatology. Nothing
 * here is generated in the browser, and the panel says plainly what the
 * backend cannot see — tides among them.
 */
import { AlertTriangle, RefreshCw, Waves, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import api from '../lib/api'
import { usePolling, useFetch } from '../hooks/useApi'
import { MONTHS } from '../lib/domain'
import { cx } from './ui'

const TONE = {
  high: {
    dot: 'bg-rose-500',
    ring: 'bg-rose-500',
    text: 'text-rose-500',
    chip: 'bg-rose-500/12 text-rose-500',
  },
  moderate: {
    dot: 'bg-amber-500',
    ring: 'bg-amber-500',
    text: 'text-amber-500',
    chip: 'bg-amber-500/12 text-amber-500',
  },
  watch: {
    dot: 'bg-amber-400',
    ring: 'bg-amber-400',
    text: 'text-faint',
    chip: 'bg-[rgb(var(--surface-sunken))] text-[rgb(var(--text-secondary))]',
  },
}

/**
 * The popup.
 *
 * Fixed to the corner rather than inline, because the point is to interrupt
 * whatever screen the operator is on. Top-right, just under the header: the
 * bottom corner is where the digital twin keeps its metrics bar, and a popup
 * that sits on top of the numbers for twelve seconds is not a warning, it is
 * an obstruction. Only high-impact lanes get one — a popup for a watch-level
 * notice trains people to close popups without reading them, and then the
 * one that matters gets closed too.
 */
function SeaStateToast({ alerts, onOpen, onClose }) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="animate-fade-in fixed right-5 top-[5.5rem] z-50 w-[21rem] overflow-hidden rounded-xl border shadow-pop"
      style={{
        backgroundColor: 'rgb(var(--surface-card))',
        borderColor: 'rgb(244 63 94 / 0.5)',
      }}
    >
      <div className="flex items-start gap-3 p-4">
        <span className="relative mt-0.5 flex h-2.5 w-2.5 shrink-0" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-500 opacity-75" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-rose-500" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-rose-500">
            {alerts.length === 1 ? 'Sea-state warning' : `${alerts.length} sea-state warnings`}
          </p>
          <ul className="mt-1 space-y-1">
            {alerts.slice(0, 3).map((alert) => (
              <li key={alert.lane} className="min-w-0">
                <p className="truncate text-xs font-medium">
                  {alert.origin} → {alert.destination}
                </p>
                <p className="text-faint numeric truncate text-[0.7rem]">{alert.detail}</p>
              </li>
            ))}
          </ul>
          {alerts.length > 3 && (
            <p className="text-faint mt-1 text-[0.7rem]">and {alerts.length - 3} more</p>
          )}
          <button
            type="button"
            onClick={onOpen}
            className="mt-2 text-xs font-medium text-primary-500 hover:underline"
          >
            View all
          </button>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Dismiss"
          className="text-faint shrink-0 rounded p-0.5 transition-colors hover:text-[rgb(var(--text-primary))]"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  )
}

export default function SeaStateAlerts() {
  // Five minutes. The server caches each marine model run for thirty, so
  // this mostly costs a cache hit; what it buys is that a gale appearing
  // mid-shift reaches the screen without anyone reloading the page.
  const { data, error, refetch } = usePolling((signal) => api.regulatory.alerts({}, { signal }), 300_000)

  const [open, setOpen] = useState(false)
  // Look ahead without moving the dot. For an Indian fleet the question is
  // "what does the south-west monsoon do to my Arabian Sea schedule in July",
  // and that is a planning question — so the panel answers it while the badge
  // keeps reporting the water as it is today. A dot that showed July's
  // conditions in September would be a warning about nothing.
  const [month, setMonth] = useState('')
  const ref = useRef(null)

  // Lanes already shouted about, so a poll every five minutes does not
  // re-announce the same gale twelve times an hour. A popup that cries wolf
  // is one an operator learns to dismiss without reading.
  const announced = useRef(new Set())
  const [toast, setToast] = useState(null)

  const outlook = useFetch(
    (signal) => (month ? api.regulatory.alerts({ month: Number(month) }, { signal }) : Promise.resolve(null)),
    [month],
  )
  const shown = month ? outlook.data : data

  useEffect(() => {
    if (!open) return undefined
    const onDown = (event) => {
      if (!ref.current?.contains(event.target)) setOpen(false)
    }
    const onKey = (event) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  useEffect(() => {
    if (!data) return
    const high = data.alerts.filter((a) => a.severity === 'high')
    const fresh = high.filter((a) => !announced.current.has(a.lane))
    high.forEach((a) => announced.current.add(a.lane))
    // Lanes that have calmed down become announceable again, so a gale that
    // returns next week still gets a popup.
    const stillHigh = new Set(high.map((a) => a.lane))
    announced.current.forEach((lane) => {
      if (!stillHigh.has(lane)) announced.current.delete(lane)
    })
    if (fresh.length) setToast({ at: Date.now(), alerts: fresh })
  }, [data])

  // Auto-dismiss. Long enough to read three lines, short enough not to sit
  // over the map; the dot stays lit afterwards, so nothing is lost.
  useEffect(() => {
    if (!toast) return undefined
    const id = window.setTimeout(() => setToast(null), 12_000)
    return () => window.clearTimeout(id)
  }, [toast])

  const mode = shown?.live?.mode ?? 'climatology'
  const worst = data?.worst_severity ?? null
  const total = data?.counts?.total ?? 0
  const tone = TONE[worst] ?? TONE.watch

  const summary = useMemo(() => {
    if (!shown) return ''
    const parts = []
    if (shown.counts.high) parts.push(`${shown.counts.high} high impact`)
    if (shown.counts.moderate) parts.push(`${shown.counts.moderate} moderate`)
    if (shown.counts.watch) parts.push(`${shown.counts.watch} watch`)
    return parts.join(' · ') || 'nothing flagged'
  }, [shown])

  // The badge always describes now, never the month being previewed.
  const badgeSummary = useMemo(() => {
    if (!data) return ''
    const parts = [
      data.counts.high && `${data.counts.high} high impact`,
      data.counts.moderate && `${data.counts.moderate} moderate`,
      data.counts.watch && `${data.counts.watch} watch`,
    ].filter(Boolean)
    if (parts.length) return parts.join(' · ')
    return data.live?.mode === 'climatology' ? 'no lane flagged' : 'all lanes clear'
  }, [data])

  // Only an unreachable API hides this — and that is the health indicator's
  // job to report. A calm sea does NOT hide it: the icon stays, quietly
  // green, so the operator can see the watch is running and can still open
  // the month outlook. The first version returned null on a calm day, which
  // made the whole feature vanish from the header the moment the live feed
  // reported clear water — indistinguishable from it having been removed.
  if (error || !data) return null
  const calm = total === 0

  return (
    <>
    {toast && (
      <SeaStateToast alerts={toast.alerts} onOpen={() => { setToast(null); setOpen(true) }} onClose={() => setToast(null)} />
    )}
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={`Sea-state alerts: ${badgeSummary}`}
        title={`Sea state · ${badgeSummary}`}
        className="relative rounded-lg p-2 transition-colors hover:bg-[rgb(var(--surface-sunken))]"
      >
        <Waves
          size={18}
          className={
            calm ? 'text-eco-500' : worst === 'high' ? 'text-rose-500' : 'text-amber-500'
          }
        />
        {/* The dot. Absent when calm, pulsing only at high impact — motion
            is the loudest thing on a screen and spending it on a watch-level
            notice means having nothing left for a gale. */}
        {!calm && (
          <span className="absolute right-1 top-1 flex h-2.5 w-2.5" aria-hidden>
            {worst === 'high' && (
              <span
                className={cx('absolute inline-flex h-full w-full animate-ping rounded-full opacity-75', tone.ring)}
              />
            )}
            <span
              className={cx(
                'relative inline-flex h-2.5 w-2.5 rounded-full ring-2 ring-[rgb(var(--surface-card))]',
                tone.dot,
              )}
            />
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Sea-state alerts"
          className="animate-fade-in absolute right-0 top-full z-40 mt-1 w-[22rem] overflow-hidden rounded-xl border shadow-pop"
          style={{
            backgroundColor: 'rgb(var(--surface-card))',
            borderColor: 'rgb(var(--border-strong))',
          }}
        >
          <div
            className="flex items-start justify-between gap-2 border-b px-4 py-3"
            style={{ borderColor: 'rgb(var(--border-subtle))' }}
          >
            <div className="min-w-0">
              <p className="flex items-center gap-1.5 text-sm font-semibold">
                <AlertTriangle size={14} className={tone.text} aria-hidden />
                Sea state
                {month && <span className="text-faint font-normal">· outlook</span>}
              </p>
              <p className="text-faint mt-0.5 text-xs">{summary}</p>
            </div>
            <div className="flex shrink-0 items-center gap-0.5">
              <button
                type="button"
                onClick={refetch}
                aria-label="Refresh alerts"
                className="text-faint rounded p-1 transition-colors hover:text-[rgb(var(--text-primary))]"
              >
                <RefreshCw size={13} />
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="text-faint rounded p-1 transition-colors hover:text-[rgb(var(--text-primary))]"
              >
                <X size={14} />
              </button>
            </div>
          </div>

          <div
            className="flex items-center gap-2 border-b px-4 py-2"
            style={{ borderColor: 'rgb(var(--border-subtle))' }}
          >
            <label className="text-faint text-[0.68rem] uppercase tracking-wide" htmlFor="sea-month">
              Month
            </label>
            <select
              id="sea-month"
              value={month}
              onChange={(event) => setMonth(event.target.value)}
              className="rounded-md border px-2 py-1 text-xs"
              style={{
                backgroundColor: 'rgb(var(--surface-sunken))',
                borderColor: 'rgb(var(--border-subtle))',
              }}
            >
              <option value="">Now — {data.month_name}</option>
              {MONTHS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
            {month && (
              <button
                type="button"
                onClick={() => setMonth('')}
                className="text-faint ml-auto text-xs hover:underline"
              >
                Back to now
              </button>
            )}
          </div>

          {shown && shown.alerts.length === 0 && (
            <p className="px-4 py-5 text-center text-xs">
              <span className="text-eco-500 font-medium">
                {month ? `No lane is flagged in ${shown.month_name}.` : 'All lanes clear.'}
              </span>
              {!month && shown.live?.mode !== 'climatology' && (
                <span className="text-faint block mt-1">
                  Live conditions are within each lane&rsquo;s normal range.
                </span>
              )}
            </p>
          )}

          <ul className="max-h-[19rem] overflow-y-auto">
            {(shown?.alerts ?? []).map((alert) => {
              const t = TONE[alert.severity] ?? TONE.watch
              return (
                <li
                  key={alert.lane}
                  className="border-b px-4 py-2.5 last:border-b-0"
                  style={{ borderColor: 'rgb(var(--border-subtle))' }}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-medium">
                      {alert.origin} → {alert.destination}
                    </span>
                    <span
                      className={cx(
                        'shrink-0 rounded px-1.5 py-0.5 text-[0.62rem] font-semibold uppercase tracking-wide',
                        t.chip,
                      )}
                    >
                      {alert.severity_label}
                    </span>
                  </div>
                  <p className={cx('numeric mt-0.5 text-xs font-medium', t.text)}>{alert.headline}</p>
                  <p className="text-faint numeric text-xs">
                    {alert.detail}
                    {/* Only where the set is mixed: with every row from the
                        same place, a chip on each one is noise. */}
                    {mode === 'mixed' && (
                      <span className={alert.source === 'observed' ? 'text-eco-500' : 'text-faint'}>
                        {' · '}
                        {alert.source === 'observed' ? 'measured' : 'estimated'}
                      </span>
                    )}
                  </p>
                </li>
              )
            })}
          </ul>

          {/* Where these numbers came from, and what they still cannot see.
              The mode is the whole value of a live feed: an operator who
              cannot tell a measured 5 m sea from an estimated one has no more
              than they had before. Said here, and repeated per row wherever
              the set is mixed. */}
          <div
            className="space-y-1.5 border-t px-4 py-2.5"
            style={{
              borderColor: 'rgb(var(--border-subtle))',
              backgroundColor: 'rgb(var(--surface-sunken))',
            }}
          >
            <p className="flex items-center gap-1.5 text-[0.68rem] font-medium">
              <span
                className={cx(
                  'h-1.5 w-1.5 shrink-0 rounded-full',
                  mode === 'observed' ? 'bg-eco-500' : mode === 'mixed' ? 'bg-amber-500' : 'bg-slate-500',
                )}
                aria-hidden
              />
              {mode === 'observed' && <span className="text-eco-500">Live marine forecast</span>}
              {mode === 'mixed' && (
                <span className="text-amber-500">
                  Live for {shown.lanes_observed} of {shown.lanes_assessed} lanes — the rest estimated
                </span>
              )}
              {mode === 'climatology' && (
                <span className="text-faint">
                  {month ? 'Seasonal outlook — estimated' : 'No live feed — estimated from climatology'}
                </span>
              )}
            </p>
            <p className="text-faint text-[0.68rem] leading-relaxed">
              {mode === 'climatology'
                ? "Each lane's registry Beaufort scaled by monthly basin climatology. Indicative, not measured."
                : `Wave height, swell and wind from ${shown.live?.provider ?? 'the marine forecast'} — ${shown.live?.attribution ?? ''}.`}{' '}
              <strong>Tides and storm surge are not modelled</strong>, so no high-tide warning is
              raised here.
            </p>
          </div>
        </div>
      )}
    </div>
    </>
  )
}
