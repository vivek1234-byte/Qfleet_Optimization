/**
 * Shared UI primitives.
 *
 * The old pages repeated the same long Tailwind class strings for every card,
 * button and input, which is why the styling drifted between them (and why
 * `hover:bg-primary-700` was broken on one page and absent on another). Every
 * screen now composes these.
 */
import { AlertTriangle, Check, Info, Loader2, X } from 'lucide-react'
import { useId } from 'react'

export const cx = (...parts) => parts.filter(Boolean).join(' ')

/* -------------------------------------------------------------------------- */
/* Layout                                                                      */
/* -------------------------------------------------------------------------- */
export function PageHeader({ title, description, actions }) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-body mt-1 max-w-2xl text-sm">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Card({ title, description, actions, footer, className, bodyClassName, children }) {
  return (
    <section className={cx('card animate-fade-in', className)}>
      {(title || actions) && (
        <header
          className="flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4"
          style={{ borderColor: 'rgb(var(--border-subtle))' }}
        >
          <div className="min-w-0">
            {title && <h2 className="truncate text-base font-semibold">{title}</h2>}
            {description && <p className="text-faint mt-0.5 text-sm">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx('p-5', bodyClassName)}>{children}</div>
      {footer && (
        <footer
          className="border-t px-5 py-3 text-sm"
          style={{ borderColor: 'rgb(var(--border-subtle))' }}
        >
          {footer}
        </footer>
      )}
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Buttons                                                                     */
/* -------------------------------------------------------------------------- */
const BUTTON_VARIANTS = {
  primary:
    'bg-primary-600 text-white hover:bg-primary-700 active:bg-primary-800 disabled:hover:bg-primary-600',
  eco: 'bg-eco-600 text-white hover:bg-eco-700 active:bg-eco-800 disabled:hover:bg-eco-600',
  secondary:
    'surface border text-[rgb(var(--text-primary))] hover:bg-[rgb(var(--surface-sunken))]',
  ghost: 'text-[rgb(var(--text-secondary))] hover:bg-[rgb(var(--surface-sunken))]',
  danger: 'bg-rose-600 text-white hover:bg-rose-700',
}

const BUTTON_SIZES = {
  sm: 'px-3 py-1.5 text-sm gap-1.5',
  md: 'px-4 py-2 text-sm gap-2',
  lg: 'px-5 py-2.5 text-base gap-2',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon: Icon,
  className,
  children,
  disabled,
  ...props
}) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        'inline-flex items-center justify-center rounded-lg font-medium transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-60',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...props}
    >
      {loading ? (
        <Loader2 size={16} className="animate-spin" aria-hidden />
      ) : (
        Icon && <Icon size={16} aria-hidden />
      )}
      {children}
    </button>
  )
}

/* -------------------------------------------------------------------------- */
/* Form fields                                                                 */
/* -------------------------------------------------------------------------- */
export function Field({ label, hint, error, children, className }) {
  return (
    <div className={className}>
      <label className="field-label">{label}</label>
      {children}
      {error ? (
        <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{error}</p>
      ) : (
        hint && <p className="text-faint mt-1 text-xs">{hint}</p>
      )}
    </div>
  )
}

export function NumberInput({ label, hint, error, unit, className, ...props }) {
  const id = useId()
  return (
    <div className={className}>
      {label && (
        <label className="field-label" htmlFor={id}>
          {label}
        </label>
      )}
      <div className="relative">
        <input
          id={id}
          type="number"
          inputMode="decimal"
          aria-invalid={error ? 'true' : undefined}
          className={cx('field-control numeric', unit && 'pr-12')}
          {...props}
        />
        {unit && (
          <span className="text-faint pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs">
            {unit}
          </span>
        )}
      </div>
      {error ? (
        <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{error}</p>
      ) : (
        hint && <p className="text-faint mt-1 text-xs">{hint}</p>
      )}
    </div>
  )
}

export function Select({ label, hint, error, options = [], className, children, ...props }) {
  const id = useId()
  return (
    <div className={className}>
      {label && (
        <label className="field-label" htmlFor={id}>
          {label}
        </label>
      )}
      <select
        id={id}
        aria-invalid={error ? 'true' : undefined}
        className="field-control appearance-none bg-[length:16px] bg-[right_0.6rem_center] bg-no-repeat pr-9"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='%2394a3b8'%3E%3Cpath d='M5.25 7.5 10 12.25 14.75 7.5' stroke='%2394a3b8' stroke-width='1.6' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\")",
        }}
        {...props}
      >
        {children ??
          options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
      </select>
      {error ? (
        <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{error}</p>
      ) : (
        hint && <p className="text-faint mt-1 text-xs">{hint}</p>
      )}
    </div>
  )
}

export function RangeInput({ label, value, unit = '%', className, ...props }) {
  const id = useId()
  return (
    <div className={className}>
      <div className="mb-1.5 flex items-baseline justify-between">
        <label className="field-label mb-0" htmlFor={id}>
          {label}
        </label>
        <span className="numeric text-sm font-semibold text-primary-600 dark:text-primary-400">
          {value}
          {unit}
        </span>
      </div>
      <input
        id={id}
        type="range"
        value={value}
        className="h-2 w-full cursor-pointer appearance-none rounded-full bg-[rgb(var(--surface-sunken))] accent-primary-600"
        {...props}
      />
    </div>
  )
}

export function Checkbox({ label, hint, className, ...props }) {
  const id = useId()
  return (
    <div className={cx('flex items-start gap-2.5', className)}>
      <input
        id={id}
        type="checkbox"
        className="mt-0.5 h-4 w-4 cursor-pointer rounded border-[rgb(var(--border-strong))] accent-primary-600"
        {...props}
      />
      <label htmlFor={id} className="cursor-pointer select-none text-sm">
        <span>{label}</span>
        {hint && <span className="text-faint block text-xs">{hint}</span>}
      </label>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Feedback                                                                    */
/* -------------------------------------------------------------------------- */
const TONES = {
  info: {
    icon: Info,
    box: 'bg-primary-50 border-primary-200 text-primary-900 dark:bg-primary-950/50 dark:border-primary-900 dark:text-primary-100',
  },
  success: {
    icon: Check,
    box: 'bg-eco-50 border-eco-200 text-eco-900 dark:bg-eco-950/50 dark:border-eco-900 dark:text-eco-100',
  },
  warning: {
    icon: AlertTriangle,
    box: 'bg-amber-50 border-amber-200 text-amber-900 dark:bg-amber-950/50 dark:border-amber-900 dark:text-amber-100',
  },
  error: {
    icon: AlertTriangle,
    box: 'bg-rose-50 border-rose-200 text-rose-900 dark:bg-rose-950/50 dark:border-rose-900 dark:text-rose-100',
  },
}

export function Alert({ tone = 'info', title, children, onDismiss, className }) {
  const { icon: Icon, box } = TONES[tone] ?? TONES.info
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cx('flex items-start gap-3 rounded-lg border p-4 text-sm', box, className)}
    >
      <Icon size={18} className="mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cx(title && 'mt-0.5', 'break-words')}>{children}</div>}
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 rounded p-0.5 opacity-60 transition-opacity hover:opacity-100"
        >
          <X size={16} />
        </button>
      )}
    </div>
  )
}

/** Renders an ApiError, including its per-field messages. */
export function ErrorState({ error, onRetry, className }) {
  if (!error) return null
  const fields = error.fields ?? []
  return (
    <Alert tone="error" title="Something went wrong" className={className}>
      <p>{error.message}</p>
      {fields.length > 0 && (
        <ul className="mt-2 list-inside list-disc space-y-0.5 text-xs">
          {fields.map((f) => (
            <li key={`${f.field}-${f.message}`}>
              <span className="font-medium">{f.field || 'request'}</span>: {f.message}
            </li>
          ))}
        </ul>
      )}
      {onRetry && (
        <Button size="sm" variant="secondary" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </Alert>
  )
}

export function EmptyState({ icon: Icon, title, description, action, className }) {
  return (
    <div className={cx('flex flex-col items-center justify-center px-6 py-14 text-center', className)}>
      {Icon && (
        <div className="mb-4 rounded-full bg-[rgb(var(--surface-sunken))] p-3.5">
          <Icon size={24} className="text-faint" aria-hidden />
        </div>
      )}
      <p className="font-medium">{title}</p>
      {description && <p className="text-faint mt-1 max-w-sm text-sm">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Skeleton({ className }) {
  return <div className={cx('skeleton', className)} aria-hidden />
}

export function Spinner({ label = 'Loading', className }) {
  return (
    <div className={cx('text-faint flex items-center justify-center gap-2 py-10 text-sm', className)}>
      <Loader2 size={18} className="animate-spin" aria-hidden />
      <span>{label}…</span>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Data display                                                                */
/* -------------------------------------------------------------------------- */
const BADGE_TONES = {
  neutral: 'bg-[rgb(var(--surface-sunken))] text-[rgb(var(--text-secondary))]',
  primary: 'bg-primary-100 text-primary-800 dark:bg-primary-900/60 dark:text-primary-200',
  eco: 'bg-eco-100 text-eco-800 dark:bg-eco-900/60 dark:text-eco-200',
  warning: 'bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200',
  danger: 'bg-rose-100 text-rose-800 dark:bg-rose-900/60 dark:text-rose-200',
}

export function Badge({ tone = 'neutral', icon: Icon, children, className }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium',
        BADGE_TONES[tone] ?? BADGE_TONES.neutral,
        className,
      )}
    >
      {Icon && <Icon size={12} aria-hidden />}
      {children}
    </span>
  )
}

const STAT_ACCENTS = {
  primary: 'bg-primary-50 text-primary-600 dark:bg-primary-950 dark:text-primary-300',
  eco: 'bg-eco-50 text-eco-600 dark:bg-eco-950 dark:text-eco-300',
  amber: 'bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-300',
  violet: 'bg-violet-50 text-violet-600 dark:bg-violet-950 dark:text-violet-300',
  slate: 'bg-[rgb(var(--surface-sunken))] text-[rgb(var(--text-secondary))]',
}

export function StatCard({
  label,
  value,
  unit,
  icon: Icon,
  accent = 'primary',
  delta,
  deltaLabel,
  loading = false,
  hint,
}) {
  const deltaTone =
    typeof delta !== 'number'
      ? null
      : delta > 0
        ? 'text-eco-600 dark:text-eco-400'
        : delta < 0
          ? 'text-rose-600 dark:text-rose-400'
          : 'text-faint'

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-faint truncate text-sm font-medium">{label}</p>
          {loading ? (
            <Skeleton className="mt-2 h-7 w-24" />
          ) : (
            <p className="numeric mt-1.5 text-2xl font-semibold tracking-tight">
              {value}
              {unit && <span className="text-faint ml-1 text-sm font-normal">{unit}</span>}
            </p>
          )}
          {!loading && typeof delta === 'number' && (
            <p className={cx('numeric mt-1.5 text-xs font-medium', deltaTone)}>
              {delta > 0 ? '▲' : delta < 0 ? '▼' : '—'} {Math.abs(delta).toFixed(1)}%
              {deltaLabel && <span className="text-faint ml-1 font-normal">{deltaLabel}</span>}
            </p>
          )}
          {!loading && hint && <p className="text-faint mt-1.5 text-xs">{hint}</p>}
        </div>
        {Icon && (
          <div className={cx('shrink-0 rounded-lg p-2.5', STAT_ACCENTS[accent] ?? STAT_ACCENTS.primary)}>
            <Icon size={20} aria-hidden />
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * A simple, accessible data table.
 *
 * Wide tables scroll inside their own container rather than pushing the page
 * body sideways.
 */
export function DataTable({ columns, rows, getRowKey, emptyMessage = 'No data', highlightRow }) {
  if (!rows?.length) {
    return <p className="text-faint py-8 text-center text-sm">{emptyMessage}</p>
  }
  return (
    <div className="-mx-5 overflow-x-auto px-5">
      <table className="w-full min-w-[36rem] border-collapse text-sm">
        <thead>
          <tr style={{ borderBottom: '1px solid rgb(var(--border-subtle))' }}>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={cx(
                  'text-faint whitespace-nowrap px-3 py-2.5 text-xs font-semibold uppercase tracking-wide',
                  col.align === 'right' ? 'text-right' : 'text-left',
                )}
                title={col.help}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={getRowKey ? getRowKey(row, index) : index}
              className={cx(
                'transition-colors hover:bg-[rgb(var(--surface-sunken))]',
                highlightRow?.(row, index) && 'bg-eco-50/60 dark:bg-eco-950/30',
              )}
              style={{ borderBottom: '1px solid rgb(var(--border-subtle))' }}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cx(
                    'px-3 py-2.5',
                    col.align === 'right' ? 'numeric text-right' : 'text-left',
                    col.className,
                  )}
                >
                  {col.render ? col.render(row, index) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Horizontal proportion bar, used for fuel mixes and feature importance. */
export function MeterRow({ label, value, max, display, tone = 'primary' }) {
  const width = max > 0 ? Math.max((value / max) * 100, 1.5) : 0
  const fill = tone === 'eco' ? 'bg-eco-500' : 'bg-primary-500'
  return (
    <div className="flex items-center gap-3">
      <span className="w-40 shrink-0 truncate text-sm" title={label}>
        {label}
      </span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-[rgb(var(--surface-sunken))]">
        <div className={cx('h-full rounded-full transition-all', fill)} style={{ width: `${width}%` }} />
      </div>
      <span className="numeric text-faint w-20 shrink-0 text-right text-xs">{display}</span>
    </div>
  )
}
