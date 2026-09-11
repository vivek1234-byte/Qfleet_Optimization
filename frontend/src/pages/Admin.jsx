/**
 * Employee administration.
 *
 * Add people, search them, edit them, revoke them, reset a password, remove
 * them. Administrators only — and the important half of that sentence is on
 * the server: every call this page makes goes to `/api/admin/*`, which is
 * behind `require_admin`. Hiding the page from an ordinary employee stops
 * them wandering into a screen full of 403s; it is not what stops them
 * managing accounts.
 *
 * Passwords are write-only throughout. Nothing on this page can read one, and
 * the API never returns a hash, so "reset" is the only recovery there is.
 */
import {
  Check,
  Eye,
  KeyRound,
  LogOut,
  Pencil,
  ScrollText,
  Search,
  ShieldCheck,
  Trash2,
  UserCheck,
  UserPlus,
  UserX,
  Users,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  Alert,
  Badge,
  Button,
  Card,
  DataTable,
  ErrorState,
  Field,
  PageHeader,
  Select,
  Skeleton,
  StatCard,
  cx,
} from '../components/ui'
import api from '../lib/api'
import { useSession } from '../lib/auth'

const EMPTY = []

// What each role can reach. Derived from the role, not stored per-user — the
// backend enforces exactly this split (employees get a 403 on /api/admin/*),
// so the matrix is a true picture of access, not a decorative checklist.
const ACCESS_AREAS = [
  { key: 'dashboard', label: 'Dashboard', roles: ['ADMIN', 'EMPLOYEE'] },
  { key: 'fleet', label: 'Fleet & lanes', roles: ['ADMIN', 'EMPLOYEE'] },
  { key: 'simulation', label: 'Live simulation', roles: ['ADMIN', 'EMPLOYEE'] },
  { key: 'optimization', label: 'Optimisation', roles: ['ADMIN', 'EMPLOYEE'] },
  { key: 'compliance', label: 'Compliance', roles: ['ADMIN', 'EMPLOYEE'] },
  { key: 'prediction', label: 'Fuel prediction', roles: ['ADMIN', 'EMPLOYEE'] },
  { key: 'scenarios', label: 'Scenarios', roles: ['ADMIN', 'EMPLOYEE'] },
  { key: 'benchmarks', label: 'Benchmarks', roles: ['ADMIN', 'EMPLOYEE'] },
  { key: 'employees', label: 'Employee management', roles: ['ADMIN'] },
]

const ROLE_OPTIONS = [
  { value: 'EMPLOYEE', label: 'Employee — voyage planning and reporting' },
  { value: 'ADMIN', label: 'Administrator — also manages accounts' },
]

const STATUS_FILTERS = [
  { value: 'all', label: 'All accounts' },
  { value: 'active', label: 'Active only' },
  { value: 'inactive', label: 'Inactive only' },
]

const ROLE_FILTERS = [
  { value: 'all', label: 'All roles' },
  { value: 'ADMIN', label: 'Administrators' },
  { value: 'EMPLOYEE', label: 'Employees' },
]

const BLANK_FORM = {
  employee_id: '',
  full_name: '',
  department: '',
  designation: '',
  role: 'EMPLOYEE',
  email: '',
  password: '',
  confirm: '',
  is_active: true,
}

/** dd MMM yyyy, without pulling in a date library for one line. */
function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
}

/** "12 Sep 2026 · 10:42", or "Never" for an account that has not signed in. */
function formatDateTime(value) {
  if (!value) return 'Never'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Never'
  const day = date.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  return `${day} · ${time}`
}

function TextField({ label, hint, error, className, ...props }) {
  return (
    <Field label={label} hint={hint} error={error} className={className}>
      <input className="field-control" {...props} />
    </Field>
  )
}

/* -------------------------------------------------------------------------- */
/* Add / edit form                                                             */
/* -------------------------------------------------------------------------- */
/**
 * Mount this with a `key` tied to what is being edited. Remounting is how the
 * fields pick up a different employee — syncing props into state with an
 * effect would render the previous person's details for a frame first.
 */
function EmployeeForm({ mode, initial, busy, serverError, onSubmit, onCancel }) {
  const [form, setForm] = useState(() => ({ ...BLANK_FORM, ...initial }))
  const [errors, setErrors] = useState({})
  const firstFieldRef = useRef(null)

  useEffect(() => {
    firstFieldRef.current?.focus()
  }, [])

  const set = (key) => (event) => {
    const value = event.target.type === 'checkbox' ? event.target.checked : event.target.value
    setForm((prev) => ({ ...prev, [key]: value }))
    setErrors((prev) => (prev[key] ? { ...prev, [key]: undefined } : prev))
  }

  const validate = () => {
    const found = {}
    const creating = mode === 'create'

    const id = form.employee_id.trim().toUpperCase()
    if (creating) {
      if (!id) found.employee_id = 'Employee ID is required.'
      else if (!/^[A-Z0-9][A-Z0-9_-]{1,31}$/.test(id))
        found.employee_id = '2–32 characters: letters, digits, dashes or underscores.'
    }

    if (!form.full_name.trim() || form.full_name.trim().length < 2)
      found.full_name = 'Full name is required.'

    if (form.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(form.email.trim()))
      found.email = 'That does not look like an email address.'

    if (creating) {
      if (!form.password) found.password = 'Password is required.'
      else if (form.password.length < 8) found.password = 'At least 8 characters.'
      if (form.password !== form.confirm) found.confirm = 'The two passwords do not match.'
    }

    setErrors(found)
    return Object.keys(found).length === 0
  }

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!validate()) return
    onSubmit({
      ...form,
      employee_id: form.employee_id.trim().toUpperCase(),
      full_name: form.full_name.trim(),
      department: form.department.trim(),
      designation: form.designation.trim(),
      email: form.email.trim() || null,
    })
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      {serverError && <ErrorState error={serverError} />}

      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="Employee ID"
          ref={mode === 'create' ? firstFieldRef : undefined}
          value={form.employee_id}
          onChange={set('employee_id')}
          disabled={busy || mode === 'edit'}
          placeholder="EMP001"
          spellCheck={false}
          autoCapitalize="characters"
          error={errors.employee_id}
          hint={
            mode === 'edit'
              ? 'The login identifier cannot be changed.'
              : 'What they will sign in with. Stored upper-case.'
          }
        />
        <TextField
          label="Full name"
          ref={mode === 'edit' ? firstFieldRef : undefined}
          value={form.full_name}
          onChange={set('full_name')}
          disabled={busy}
          placeholder="Priya Nair"
          error={errors.full_name}
        />
        <TextField
          label="Department"
          value={form.department}
          onChange={set('department')}
          disabled={busy}
          placeholder="Voyage Planning"
          error={errors.department}
        />
        <TextField
          label="Designation"
          value={form.designation}
          onChange={set('designation')}
          disabled={busy}
          placeholder="Fleet Manager"
          hint="Job title. Separate from the access role below."
          error={errors.designation}
        />
        <Select
          label="Role"
          value={form.role}
          onChange={set('role')}
          disabled={busy}
          options={ROLE_OPTIONS}
          hint={
            form.role === 'ADMIN'
              ? 'Administrators can add, edit and remove any account, including yours.'
              : undefined
          }
        />
        <TextField
          label="Email (optional)"
          type="email"
          value={form.email ?? ''}
          onChange={set('email')}
          disabled={busy}
          placeholder="priya.nair@operator.com"
          spellCheck={false}
          error={errors.email}
          className="sm:col-span-2"
        />
      </div>

      {mode === 'create' && (
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Password"
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={set('password')}
            disabled={busy}
            error={errors.password}
            hint="At least 8 characters. Give it to them over a trusted channel."
          />
          <TextField
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            value={form.confirm}
            onChange={set('confirm')}
            disabled={busy}
            error={errors.confirm}
          />
        </div>
      )}

      <label className="flex cursor-pointer select-none items-center gap-2.5 text-sm">
        <input
          type="checkbox"
          checked={form.is_active}
          onChange={set('is_active')}
          disabled={busy}
          className="h-4 w-4 cursor-pointer rounded border-[rgb(var(--border-strong))] accent-primary-600"
        />
        <span className="text-body">
          Active — can sign in. Clear this to revoke access without deleting the record.
        </span>
      </label>

      <div className="flex flex-wrap gap-2 pt-1">
        <Button type="submit" loading={busy} icon={mode === 'create' ? UserPlus : Pencil}>
          {mode === 'create' ? 'Add employee' : 'Save changes'}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

/* -------------------------------------------------------------------------- */
/* Password reset                                                              */
/* -------------------------------------------------------------------------- */
function ResetPasswordForm({ employee, busy, serverError, onSubmit, onCancel }) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState(null)

  const handleSubmit = (event) => {
    event.preventDefault()
    if (password.length < 8) return setError('At least 8 characters.')
    if (password !== confirm) return setError('The two passwords do not match.')
    setError(null)
    onSubmit(password)
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      {serverError && <ErrorState error={serverError} />}
      <p className="text-body text-sm">
        Set a new password for <strong>{employee.employee_id}</strong> ({employee.full_name}). Their
        existing password stops working immediately; sessions already signed in on other devices
        stay valid until they expire.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={busy}
          autoFocus
        />
        <TextField
          label="Confirm"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          disabled={busy}
          error={error}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={busy} icon={KeyRound}>
          Reset password
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */
export default function Admin() {
  const { session } = useSession()

  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)

  // 'none' | 'create' | 'edit' | 'reset'
  const [panel, setPanel] = useState('none')
  const [target, setTarget] = useState(null)
  // The read-only detail drawer overlays everything else, so it has its own
  // state rather than sharing `panel`.
  const [viewing, setViewing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState(null)
  const [flash, setFlash] = useState(null)

  // A keystroke per character would be a request per character.
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(search), 250)
    return () => window.clearTimeout(id)
  }, [search])

  const load = useCallback(
    async (signal) => {
      setLoading(true)
      setLoadError(null)
      try {
        const params = { search: debounced }
        if (roleFilter !== 'all') params.role = roleFilter
        if (statusFilter !== 'all') params.active = statusFilter === 'active'
        const result = await api.admin.employees(params, { signal })
        setData(result)
      } catch (error) {
        if (!error?.cancelled) setLoadError(error)
      } finally {
        setLoading(false)
      }
    },
    [debounced, roleFilter, statusFilter],
  )

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

  const refresh = () => load()

  const employees = data?.employees ?? EMPTY

  const closePanel = () => {
    setPanel('none')
    setTarget(null)
    setFormError(null)
  }

  /** Run a mutation, then reload. One place for the busy/error/flash dance. */
  const mutate = async (fn, message) => {
    setBusy(true)
    setFormError(null)
    try {
      await fn()
      setFlash(message)
      closePanel()
      await load()
    } catch (error) {
      setFormError(error)
    } finally {
      setBusy(false)
    }
  }

  const handleCreate = (form) =>
    mutate(
      () =>
        api.admin.createEmployee({
          employee_id: form.employee_id,
          full_name: form.full_name,
          department: form.department,
          designation: form.designation,
          role: form.role,
          email: form.email,
          password: form.password,
          is_active: form.is_active,
        }),
      `${form.employee_id} added.`,
    )

  const handleUpdate = (form) =>
    mutate(
      () =>
        api.admin.updateEmployee(target.id, {
          full_name: form.full_name,
          department: form.department,
          designation: form.designation,
          role: form.role,
          email: form.email,
          is_active: form.is_active,
        }),
      `${target.employee_id} updated.`,
    )

  const handleReset = (password) =>
    mutate(
      () => api.admin.resetPassword(target.id, { new_password: password }),
      `Password reset for ${target.employee_id}.`,
    )

  const toggleActive = (employee) =>
    mutate(
      () =>
        employee.is_active
          ? api.admin.deactivate(employee.id)
          : api.admin.activate(employee.id),
      `${employee.employee_id} ${employee.is_active ? 'deactivated' : 'reactivated'}.`,
    )

  const handleRevoke = (employee) => {
    // eslint-disable-next-line no-alert
    const confirmed = window.confirm(
      `Sign ${employee.employee_id} (${employee.full_name}) out of every device?\n\n` +
        'Their password still works — they can sign straight back in. Use this for ' +
        'a lost phone or a terminal someone forgot to sign out of.',
    )
    if (!confirmed) return
    mutate(
      () => api.admin.revokeSessions(employee.id),
      `${employee.employee_id} signed out everywhere.`,
    )
  }

  const handleDelete = (employee) => {
    // eslint-disable-next-line no-alert
    const confirmed = window.confirm(
      `Delete ${employee.employee_id} (${employee.full_name})?\n\n` +
        'This removes the record entirely. To revoke access but keep the history, ' +
        'deactivate the account instead.',
    )
    if (!confirmed) return
    mutate(() => api.admin.deleteEmployee(employee.id), `${employee.employee_id} deleted.`)
  }

  const columns = useMemo(
    () => [
      {
        key: 'employee_id',
        header: 'Employee ID',
        render: (row) => (
          <span className="numeric font-medium">
            {row.employee_id}
            {row.id === session?.employee?.id && (
              <span className="text-faint ml-2 text-xs font-normal">(you)</span>
            )}
          </span>
        ),
      },
      {
        key: 'full_name',
        header: 'Name',
        render: (row) => <span className="font-medium">{row.full_name}</span>,
      },
      {
        key: 'email',
        header: 'Email',
        render: (row) =>
          row.email ? (
            <span className="text-body text-xs">{row.email}</span>
          ) : (
            <span className="text-faint text-xs">—</span>
          ),
      },
      { key: 'department', header: 'Department', render: (row) => row.department || '—' },
      {
        key: 'designation',
        header: 'Designation',
        render: (row) =>
          row.designation ? (
            row.designation
          ) : (
            <span className="text-faint">—</span>
          ),
      },
      {
        key: 'role',
        header: 'Role',
        render: (row) =>
          row.role === 'ADMIN' ? (
            <Badge tone="primary" icon={ShieldCheck}>
              Administrator
            </Badge>
          ) : (
            <Badge tone="neutral">Employee</Badge>
          ),
      },
      {
        key: 'is_active',
        header: 'Status',
        render: (row) =>
          row.is_active ? (
            <Badge tone="eco">Active</Badge>
          ) : (
            <Badge tone="danger">Inactive</Badge>
          ),
      },
      {
        key: 'last_login',
        header: 'Last login',
        render: (row) => (
          <span className="text-faint whitespace-nowrap text-xs">
            {formatDateTime(row.last_login)}
          </span>
        ),
      },
      {
        key: 'actions',
        header: '',
        align: 'right',
        render: (row) => {
          const isSelf = row.id === session?.employee?.id
          return (
            <div className="flex justify-end gap-1">
              <IconAction
                label={`View ${row.employee_id}`}
                icon={Eye}
                onClick={() => setViewing(row)}
              />
              <IconAction
                label={`Edit ${row.employee_id}`}
                icon={Pencil}
                onClick={() => {
                  setTarget(row)
                  setPanel('edit')
                  setFormError(null)
                }}
              />
              <IconAction
                label={`Reset password for ${row.employee_id}`}
                icon={KeyRound}
                onClick={() => {
                  setTarget(row)
                  setPanel('reset')
                  setFormError(null)
                }}
              />
              <IconAction
                label={`Sign ${row.employee_id} out of every device`}
                icon={LogOut}
                onClick={() => handleRevoke(row)}
              />
              <IconAction
                label={`${row.is_active ? 'Deactivate' : 'Reactivate'} ${row.employee_id}`}
                icon={row.is_active ? UserX : UserCheck}
                disabled={isSelf}
                title={isSelf ? 'You cannot deactivate your own account' : undefined}
                onClick={() => toggleActive(row)}
              />
              <IconAction
                label={`Delete ${row.employee_id}`}
                icon={Trash2}
                tone="danger"
                disabled={isSelf}
                title={isSelf ? 'You cannot delete your own account' : undefined}
                onClick={() => handleDelete(row)}
              />
            </div>
          )
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [session?.employee?.id],
  )

  return (
    <div>
      <PageHeader
        title="Employee Management"
        description="Manage workforce access, roles and account status."
        actions={
          <Button
            icon={UserPlus}
            onClick={() => {
              setTarget(null)
              setPanel(panel === 'create' ? 'none' : 'create')
              setFormError(null)
            }}
          >
            Add employee
          </Button>
        }
      />

      {flash && (
        <Alert tone="success" className="mb-5" onDismiss={() => setFlash(null)}>
          {flash}
        </Alert>
      )}

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total employees"
          value={data ? String(data.total) : '—'}
          icon={Users}
          accent="primary"
          loading={loading && !data}
        />
        <StatCard
          label="Active"
          value={data ? String(data.active) : '—'}
          icon={UserCheck}
          accent="eco"
          loading={loading && !data}
        />
        <StatCard
          label="Administrators"
          value={data ? String(data.admins) : '—'}
          icon={ShieldCheck}
          accent="violet"
          loading={loading && !data}
        />
        <StatCard
          label="Inactive accounts"
          value={data ? String(data.inactive) : '—'}
          icon={UserX}
          accent="amber"
          loading={loading && !data}
        />
      </div>

      {panel === 'create' && (
        <Card
          title="Add an employee"
          description="They can sign in as soon as you save. Nobody can read this password back, including you — if it is lost, reset it."
          className="mb-6"
        >
          <EmployeeForm
            key="create"
            mode="create"
            initial={BLANK_FORM}
            busy={busy}
            serverError={formError}
            onSubmit={handleCreate}
            onCancel={closePanel}
          />
        </Card>
      )}

      {panel === 'edit' && target && (
        <Card title={`Edit ${target.employee_id}`} className="mb-6">
          <EmployeeForm
            key={`edit-${target.id}`}
            mode="edit"
            initial={{
              employee_id: target.employee_id,
              full_name: target.full_name,
              department: target.department ?? '',
              designation: target.designation ?? '',
              role: target.role,
              email: target.email ?? '',
              is_active: target.is_active,
            }}
            busy={busy}
            serverError={formError}
            onSubmit={handleUpdate}
            onCancel={closePanel}
          />
        </Card>
      )}

      {panel === 'reset' && target && (
        <Card title={`Reset password — ${target.employee_id}`} className="mb-6">
          <ResetPasswordForm
            key={`reset-${target.id}`}
            employee={target}
            busy={busy}
            serverError={formError}
            onSubmit={handleReset}
            onCancel={closePanel}
          />
        </Card>
      )}

      <Card
        title="Directory"
        description="Search matches Employee ID, name, department and email."
        actions={
          <Button variant="ghost" size="sm" onClick={refresh} disabled={loading}>
            Refresh
          </Button>
        }
      >
        <div className="mb-4 grid gap-3 sm:grid-cols-[1fr_auto_auto]">
          <div className="relative">
            <Search
              size={16}
              className="text-faint pointer-events-none absolute left-3 top-1/2 -translate-y-1/2"
              aria-hidden
            />
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search employees"
              aria-label="Search employees"
              className="field-control pl-9"
            />
          </div>
          <Select
            value={roleFilter}
            onChange={(event) => setRoleFilter(event.target.value)}
            options={ROLE_FILTERS}
            aria-label="Filter by role"
          />
          <Select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            options={STATUS_FILTERS}
            aria-label="Filter by status"
          />
        </div>

        {loadError ? (
          <ErrorState error={loadError} onRetry={refresh} />
        ) : loading && !data ? (
          <div className="space-y-2">
            {[0, 1, 2, 3, 4].map((row) => (
              <Skeleton key={row} className="h-11 w-full" />
            ))}
          </div>
        ) : (
          <DataTable
            columns={columns}
            rows={employees}
            getRowKey={(row) => row.id}
            emptyMessage={
              debounced || roleFilter !== 'all' || statusFilter !== 'all'
                ? 'No employee matches those filters.'
                : 'No employees yet. Add the first one above.'
            }
          />
        )}
      </Card>

      <AuditPanel flashKey={flash} />

      <p className="text-faint mt-6 text-xs leading-relaxed">
        Passwords are stored only as bcrypt hashes and are never returned by the API, so there is
        no way to look one up — only to set a new one. Resetting a password, signing someone out
        and deactivating an account all end every session that person currently has, on every
        device, immediately.
      </p>

      {viewing && (
        <EmployeeDrawer
          employee={viewing}
          isSelf={viewing.id === session?.employee?.id}
          onClose={() => setViewing(null)}
          onEdit={() => {
            setTarget(viewing)
            setPanel('edit')
            setFormError(null)
            setViewing(null)
          }}
          onReset={() => {
            setTarget(viewing)
            setPanel('reset')
            setFormError(null)
            setViewing(null)
          }}
          onToggleActive={() => {
            const employee = viewing
            setViewing(null)
            toggleActive(employee)
          }}
        />
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Detail drawer                                                               */
/* -------------------------------------------------------------------------- */
function DetailRow({ label, children }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="text-faint shrink-0 text-xs uppercase tracking-wide">{label}</dt>
      <dd className="min-w-0 text-right text-sm">{children}</dd>
    </div>
  )
}

/**
 * Read-only employee profile, as a right-hand drawer.
 *
 * The ACCESS block is derived from the role against the same map the backend
 * enforces — it is a true statement of what this person can reach, not a
 * cosmetic checklist. No password material appears here; the API never returns
 * any, so there is none to show.
 */
function EmployeeDrawer({ employee, isSelf, onClose, onEdit, onReset, onToggleActive }) {
  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const initials =
    (employee.full_name ?? '')
      .split(' ')
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join('') || '?'

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close panel"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <aside
        className="animate-fade-in surface relative flex h-full w-full max-w-md flex-col overflow-y-auto border-l shadow-pop"
        role="dialog"
        aria-label={`${employee.full_name} profile`}
      >
        <header
          className="flex items-start gap-3 border-b p-5"
          style={{ borderColor: 'rgb(var(--border-subtle))' }}
        >
          <span
            className="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-primary-600 text-sm font-semibold text-white"
            aria-hidden
          >
            {initials}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-base font-semibold">{employee.full_name}</p>
            <p className="numeric text-faint text-xs">
              {employee.employee_id}
              {isSelf && <span className="ml-2">(you)</span>}
            </p>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {employee.role === 'ADMIN' ? (
                <Badge tone="primary" icon={ShieldCheck}>
                  Administrator
                </Badge>
              ) : (
                <Badge tone="neutral">Employee</Badge>
              )}
              {employee.is_active ? (
                <Badge tone="eco">Active</Badge>
              ) : (
                <Badge tone="danger">Inactive</Badge>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close panel"
            className="rounded-md p-1.5 text-[rgb(var(--text-muted))] transition-colors hover:bg-[rgb(var(--surface-sunken))]"
          >
            <X size={18} />
          </button>
        </header>

        <div className="flex-1 space-y-5 p-5">
          <section>
            <h3 className="text-faint mb-1 text-xs font-semibold uppercase tracking-wide">
              Contact
            </h3>
            <dl className="divide-y" style={{ borderColor: 'rgb(var(--border-subtle))' }}>
              <DetailRow label="Email">{employee.email || '—'}</DetailRow>
              <DetailRow label="Department">{employee.department || '—'}</DetailRow>
              <DetailRow label="Designation">{employee.designation || '—'}</DetailRow>
            </dl>
          </section>

          <section>
            <h3 className="text-faint mb-1 text-xs font-semibold uppercase tracking-wide">
              Account
            </h3>
            <dl className="divide-y" style={{ borderColor: 'rgb(var(--border-subtle))' }}>
              <DetailRow label="Status">{employee.is_active ? 'Active' : 'Inactive'}</DetailRow>
              <DetailRow label="Last login">
                <span className="numeric">{formatDateTime(employee.last_login)}</span>
              </DetailRow>
              <DetailRow label="Created">
                <span className="numeric">{formatDate(employee.created_at)}</span>
              </DetailRow>
            </dl>
          </section>

          <section>
            <h3 className="text-faint mb-2 text-xs font-semibold uppercase tracking-wide">Access</h3>
            <ul className="space-y-1.5">
              {ACCESS_AREAS.map((area) => {
                const allowed = area.roles.includes(employee.role)
                return (
                  <li key={area.key} className="flex items-center justify-between gap-3 text-sm">
                    <span>{area.label}</span>
                    {allowed ? (
                      <Check size={16} className="text-eco-500" aria-label="Allowed" />
                    ) : (
                      <X size={16} className="text-[rgb(var(--text-muted))]" aria-label="No access" />
                    )}
                  </li>
                )
              })}
            </ul>
            <p className="text-faint mt-2 text-xs">
              Derived from the role and enforced by the server — an employee calling an admin API
              is refused with 403 regardless of what any screen shows.
            </p>
          </section>
        </div>

        <footer
          className="flex flex-wrap gap-2 border-t p-4"
          style={{ borderColor: 'rgb(var(--border-subtle))' }}
        >
          <Button size="sm" icon={Pencil} onClick={onEdit}>
            Edit
          </Button>
          <Button size="sm" variant="secondary" icon={KeyRound} onClick={onReset}>
            Reset password
          </Button>
          <Button
            size="sm"
            variant="ghost"
            icon={employee.is_active ? UserX : UserCheck}
            onClick={onToggleActive}
            disabled={isSelf && employee.is_active}
            title={
              isSelf && employee.is_active ? 'You cannot deactivate your own account' : undefined
            }
          >
            {employee.is_active ? 'Deactivate' : 'Reactivate'}
          </Button>
        </footer>
      </aside>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Audit log                                                                   */
/* -------------------------------------------------------------------------- */
/**
 * A read-only feed of administrator actions. Reloads whenever `flashKey`
 * changes — that string flips on every successful mutation on this page, so a
 * newly created or deactivated account shows up in the log without a manual
 * refresh.
 */
function AuditPanel({ flashKey }) {
  const [entries, setEntries] = useState(EMPTY)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    api.admin
      .audit({ limit: 40 }, { signal: controller.signal })
      .then((data) => {
        setEntries(data.entries ?? EMPTY)
        setError(null)
      })
      .catch((err) => {
        if (!err?.cancelled) setError(err)
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [flashKey])

  return (
    <Card
      title="Activity log"
      description="Administrator actions on accounts, newest first. Never records passwords."
      className="mt-6"
      actions={<ScrollText size={16} className="text-faint" aria-hidden />}
    >
      {error ? (
        <ErrorState error={error} />
      ) : loading && entries.length === 0 ? (
        <div className="space-y-2">
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-9 w-full" />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <p className="text-faint py-4 text-center text-sm">
          No administrator actions recorded yet.
        </p>
      ) : (
        <DataTable
          columns={[
            {
              key: 'created_at',
              header: 'When',
              render: (row) => (
                <span className="text-faint whitespace-nowrap text-xs">
                  {formatDateTime(row.created_at)}
                </span>
              ),
            },
            {
              key: 'actor',
              header: 'Administrator',
              render: (row) => <span className="numeric text-sm">{row.actor}</span>,
            },
            { key: 'action', header: 'Action', render: (row) => row.action },
            {
              key: 'target',
              header: 'Target',
              render: (row) =>
                row.target ? (
                  <span className="numeric text-sm">{row.target}</span>
                ) : (
                  <span className="text-faint">—</span>
                ),
            },
            {
              key: 'result',
              header: 'Result',
              render: (row) => (
                <Badge tone={row.result === 'Success' ? 'eco' : 'danger'}>{row.result}</Badge>
              ),
            },
          ]}
          rows={entries}
          getRowKey={(row) => row.id}
        />
      )}
    </Card>
  )
}

function IconAction({ label, icon: Icon, onClick, disabled, title, tone = 'neutral' }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={title ?? label}
      className={cx(
        'rounded-md p-1.5 transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        tone === 'danger'
          ? 'text-[rgb(var(--text-muted))] hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950/40 dark:hover:text-rose-400'
          : 'text-[rgb(var(--text-muted))] hover:bg-[rgb(var(--surface-sunken))] hover:text-[rgb(var(--text-primary))]',
      )}
    >
      <Icon size={16} />
    </button>
  )
}
