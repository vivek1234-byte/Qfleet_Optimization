# Security review — Employee ID authentication

A review of the sign-in and account system added in `backend/auth`, `backend/admin`
and `frontend/src/lib/auth.js`, plus what has to change before the platform is
split by agency.

**Caveat worth stating first:** this is a self-review. The same person wrote the
code and the review, which catches mechanical mistakes and misses assumptions.
Before this carries real accounts, someone else should read `auth/deps.py`,
`auth/api.py` and `admin/api.py` cold.

---

> **Status, updated after the first round of fixes.** Findings 1, 5, 6 and
> most of the Medium list are now implemented and tested — see *What was
> fixed* below. Findings 2, 3, 4 and 7 (open API routes, TLS, `localStorage`,
> MFA) are still open, and so is the whole tenancy section.

## Verdict

**The authentication mechanics are sound. The deployment posture is not, and
there is no tenancy at all.**

Concretely: how a password is stored and checked, how a failed login answers,
and where authorization is enforced — those are right, and there are tests that
fail if they stop being right. What is missing is everything around them. There
is no rate limiting, no transport security, no token revocation, and the rest of
the API has no authentication on it. For a demo on `127.0.0.1` that is fine. The
moment it is on a network with real staff behind it, four of the items below are
the difference between "has a login" and "is secure".

---

## What holds up

| Control | Implementation | Verified by |
| --- | --- | --- |
| Password storage | bcrypt, cost 12, per-hash salt. Never stored, returned or logged in plain text | `TestPasswordHashing` |
| Hash never leaves the API | Every response is built by `EmployeeOut`, which lists fields by name — no model dumping, so a new column cannot leak | `test_response_never_carries_the_hash`, `test_list_never_includes_a_hash` |
| No account enumeration | Identical status, code and message for unknown ID vs wrong password; `dummy_verify()` burns an equivalent bcrypt so timing matches; no client-side ID format check | `test_no_account_enumeration`, `test_error_never_names_the_employee` |
| Authorization at the API | `require_admin` declared on the **router**, so a route added later is protected by construction | every route parametrised in `TestRoleEnforcement`, plus a test that fails if the dependency is moved |
| Immediate revocation on deactivate | `get_current_employee` re-reads the row per request instead of trusting token claims | `test_deactivation_ends_a_live_session` |
| No mass assignment | `extra="forbid"` on every request schema — `password_hash` or `role` cannot be smuggled into a create call | `test_unknown_field_is_rejected` |
| No SQL injection | SQLAlchemy ORM throughout; the search `LIKE` pattern is a bound parameter | — |
| No CSRF | Bearer token in a header, not a cookie, so a cross-site form post carries no credential | — |
| Lockout guards | Last active administrator cannot be demoted, deactivated or deleted; nobody can do any of the three to themselves | `TestLockoutGuards` |

---

## What does not hold up

### Critical

**1. No rate limiting and no account lockout.**
`POST /api/auth/login` accepts unlimited attempts. bcrypt at cost 12 is about
250 ms, so one connection gets ~4 guesses a second — but nothing stops a hundred
concurrent connections, which is ~400/s, and an 8-character password does not
survive that for long. The same gap is a denial-of-service vector in the other
direction: bcrypt is deliberately CPU-expensive, so unauthenticated login spam
pins every core and takes the optimiser down with it.

This is the single most important fix and the cheapest one.

**2. Every other API route is unauthenticated.**
`/api/optimization`, `/api/prediction`, `/api/benchmarks`, `/api/scenarios` and
`/api/regulatory` have no auth at all. Anyone who can reach the port has the
whole product without signing in. Today the server binds to `127.0.0.1`, so this
is a landmine rather than a live hole — but "we'll remember to fix it when we
deploy" is how it ships.

The reason it was left open is real and still stands: `/api/optimization/stream`
is consumed with `EventSource`, which cannot send an `Authorization` header. Fix
№6 below dissolves that problem.

**3. No TLS.**
Employee ID and password travel in a POST body. Over plain HTTP on a shared
network that is plaintext credentials, and the bearer token that comes back is
equally readable. Nothing in the codebase enforces or even expects HTTPS.

### High

**4. The session token lives in `localStorage`.**
Any successful XSS reads it and exfiltrates it, and a stolen token is valid for
up to 12 hours with no way to revoke it. `httpOnly` + `Secure` + `SameSite=Lax`
cookies would put it out of JavaScript's reach.

**5. There is no token revocation, and one message currently lies about it.**
Tokens are stateless. Logout is a client-side discard, which the code documents
honestly. But `POST /api/auth/change-password` returns:

> "Password changed. Sign in again on your other devices."

That sentence implies other sessions were ended. They were not — every token
issued before the change keeps working until it expires. Someone who changes
their password *because* they think it was compromised is being told they are
safe when they are not. Either the copy or the behaviour has to change, and the
behaviour is the right one to change (fix №7).

**6. An admin-set password is never forced to change.**
After `reset-password`, the administrator knows the employee's password and the
employee is never prompted to replace it. There is also no strength requirement
beyond eight characters and no breached-password check, so `password` passes.

**7. No MFA anywhere**, including for administrator accounts that can create and
delete every other account.

### Medium

- **Inactive accounts announce themselves.** `QGF_DISCLOSE_INACTIVE` defaults to
  `true`, so "Account is inactive" confirms an Employee ID exists. This was a
  deliberate usability trade and it is documented — but the default should flip
  to `false` in production, where the enumeration matters more than the hint.
- **No audit trail that survives a restart.** Sign-ins, failures, account
  creation and password resets go to the application log and nowhere else. An
  operations platform wants those rows in the database, queryable, with actor,
  target, action and time.
- **Failed logins log the Employee ID** (`auth/api.py`), so the log file
  accumulates a partial staff directory. Log the hash prefix or a request id.
- **No security headers.** No HSTS, CSP, `X-Content-Type-Options` or
  `X-Frame-Options` anywhere in the middleware stack.
- **Fixed 12-hour token, no idle timeout and no refresh.** A laptop left open in
  a port office stays signed in all day.
- **Seeded demo passwords are in a public repository.** `manage seed` will
  happily create `EMP001 / Admin@12345` against a production database.

### Low

- The admin search passes user input into a `LIKE` pattern, so `%` and `_`
  behave as wildcards. Not injection — the value is bound — just surprising.
- The JWT carries no `aud` and no `jti`, which forecloses audience separation
  and per-token revocation later.

---

## What was fixed

Implemented and covered by tests after the review above.

| Was | Now |
| --- | --- |
| Unlimited login attempts | Sliding-window limiter, 8 failures per Employee ID and 30 per client address over 5 minutes, checked **before** the bcrypt so a throttled request costs nothing. A correct password clears both counters. `429` with `Retry-After`; the login page shows a live countdown. `backend/auth/ratelimit.py` |
| Password change did not end other sessions, and the message said it did | `employees.token_version`, carried in the token as `tv` and compared on every request. Changing a password, resetting one, or a forced sign-out strands every token already issued. The caller gets a replacement token so they are not signed out of the device in front of them. |
| No way to end a stolen session | `POST /api/auth/logout-everywhere` for yourself; `POST /api/admin/employees/{id}/revoke-sessions` and a button on the Employees page for an administrator. Plain logout still only signs out this device — a shared terminal should not kick you off your phone. |
| Any 8 characters accepted | Blocklist of the passwords at the top of every breach corpus, plus rejection of the account's own Employee ID or name — the commonest weak password in a staff system and the one no generic list catches. `security.password_problem` |
| Disabled accounts announced themselves | `QGF_DISCLOSE_INACTIVE` now defaults to **false**: a disabled account fails byte-identically to a wrong password. The kinder message is still available per deployment. |
| No security headers | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` and a deny-all CSP on every response; `Cache-Control: no-store` on `/api/auth` and `/api/admin`. HSTS behind `QGF_HSTS_ENABLED`, off by default because on plain-http localhost it pins the origin. |
| `manage seed` would create published demo passwords anywhere | Refuses unless `QGF_DEBUG=true` or `--force`. The launchers pass `--force`, because they *are* the development entry point; production uses `bootstrap`. |
| Caps Lock silently ate correct passwords | The login page warns, announced through `aria-describedby`. Cheaper than a failed attempt against the limiter. |
| A revoked session bounced to `/login` with no explanation | The server's reason ("Your session was ended. Sign in again.") is carried through the redirect and shown. |

**Still open from the list above:** finding 2 (the optimisation, prediction,
benchmark, scenario and regulatory routers are still unauthenticated),
finding 3 (TLS), finding 4 (token in `localStorage`) and finding 7 (MFA).
Fixes 4 and 2 are one piece of work — moving the session into an
`httpOnly` cookie is what lets `EventSource` authenticate, which is the only
reason those routers were left open.

---

## Splitting the platform by agency

Today there is exactly one tenant. `employees.employee_id` is globally unique,
there is no organisation table, and every signed-in employee sees the same 20
vessels and 16 lanes. "Divided in agencies" means fixing that, and the auth
layer is only half of it.

### Schema

```sql
CREATE TABLE agencies (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(16)  NOT NULL UNIQUE,   -- short login prefix, e.g. MSCIN
    name        VARCHAR(120) NOT NULL,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

ALTER TABLE employees ADD COLUMN agency_id INTEGER NOT NULL REFERENCES agencies(id);

-- The important line: an Employee ID is unique WITHIN an agency, not globally.
DROP INDEX ix_employees_employee_id;
CREATE UNIQUE INDEX ix_employees_agency_employee_id ON employees (agency_id, employee_id);
```

### Roles become three tiers

| Role | Scope | Can |
| --- | --- | --- |
| `PLATFORM_ADMIN` | all agencies | create and suspend agencies; create the first admin of each |
| `AGENCY_ADMIN` | one agency | everything the current ADMIN does, within their agency only |
| `EMPLOYEE` | one agency | use the platform within their agency |

`PLATFORM_ADMIN` is you, the operator — not a customer role. Keep the number of
these accounts in single digits and put MFA on them first.

### Sign-in

Employee IDs stop being globally unique, so the login form needs to identify the
agency. Three options, in order of preference:

1. **A third field: Agency code.** `MSCIN / EMP001 / password`. One more input
   above Employee ID; the existing layout absorbs it without redesign. Simplest
   and honest about what is happening.
2. **A subdomain per agency** — `mscin.qfleet.app` — resolved server-side from
   the `Host` header, so the form stays two fields. Nicer, needs DNS and
   per-tenant routing.
3. Keep IDs globally unique and prefix them (`MSCIN-EMP001`). No real tenancy in
   the schema, just a naming convention. Avoid — it breaks the first time two
   agencies pick the same scheme.

Go with (1) now, (2) when there is a domain.

### Enforcement — the part that actually matters

Every multi-tenant breach is the same bug: one query that forgot
`WHERE agency_id = ?`. Do not rely on remembering.

**Derive the agency from the database row, never from the token.**
`get_current_employee` already re-reads the employee row, so use
`employee.agency_id`. A token claim is only as trustworthy as the signing key;
the row is authoritative.

**Make the scoped query the only convenient one.** A dependency that returns a
pre-filtered query, and a review rule that routes never call `select(Model)`
directly:

```python
def scoped(model, employee: Employee = Depends(get_current_employee)):
    stmt = select(model)
    if employee.role != Role.PLATFORM_ADMIN.value:
        stmt = stmt.where(model.agency_id == employee.agency_id)
    return stmt
```

**On PostgreSQL, add Row-Level Security.** This is the highest-value item in
this whole document, because it makes the forgotten filter return nothing
instead of another agency's data:

```sql
ALTER TABLE employees ENABLE ROW LEVEL SECURITY;
CREATE POLICY agency_isolation ON employees
    USING (agency_id = current_setting('app.agency_id')::int);
```

with `SET LOCAL app.agency_id = …` at the start of each request transaction. It
is a second reason to move off SQLite for production — SQLite has no equivalent.

**Test it adversarially.** Create two agencies, then for every list, get, update
and delete route, assert that agency B's token gets 404 or 403 against agency
A's object id. Parametrise it the way `TestRoleEnforcement` already parametrises
the admin routes — the point is that adding a route without a cross-tenant test
should be the thing that fails.

### The part that is bigger than auth

`backend/data/fleet_registry.py` is a static 20-vessel list shared by every
caller. Real agencies need their own vessels, lanes, voyages and saved plans,
which means `agency_id` on those tables too and a migration path off the static
registry. That is a larger change than the account system and should be planned
as its own piece of work rather than bolted onto this one.

---

## Order of work

**Before the demo** — ~~hours~~ **done**, see *What was fixed* above.

| | Fix | |
| 1 | Rate limit `POST /api/auth/login` — per IP and per Employee ID | done |
| 2 | Make the change-password message true (`token_version`) | done |
| 3 | Make `manage seed` refuse unless `QGF_DEBUG=true` | done |
| 4 | Security-headers middleware | done |
| 5 | Flip `QGF_DISCLOSE_INACTIVE` to `false` by default | done |

**Before anyone real signs in**

| | Fix |
| 6 | TLS, HSTS, and a cookie-based session (`httpOnly`/`Secure`/`SameSite`) instead of `localStorage` — this also lets `EventSource` authenticate, which unblocks fix 8 |
| 7 | ~~`token_version` column~~ — done |
| 8 | Authentication on the optimisation, prediction, benchmark, scenario and regulatory routers |
| 9 | Persisted audit log: actor, action, target, timestamp, source address |
| 10 | Force a password change after an admin reset; add a breached-password check |
| 11 | MFA for `PLATFORM_ADMIN` and `AGENCY_ADMIN` |
| 12 | PostgreSQL, the agency schema above, and Row-Level Security |

### Fix 1, concretely

```python
# backend/auth/ratelimit.py
from collections import defaultdict
from time import monotonic

_attempts: dict[str, list[float]] = defaultdict(list)
WINDOW_SECONDS = 300
MAX_ATTEMPTS = 10

def check(key: str) -> None:
    """Raise if `key` has failed too often recently. Call on failure only."""
    now = monotonic()
    recent = [t for t in _attempts[key] if now - t < WINDOW_SECONDS]
    _attempts[key] = recent
    if len(recent) >= MAX_ATTEMPTS:
        raise AuthenticationError(
            "Too many attempts. Try again in a few minutes.",
            status_code=429,
            code="RATE_LIMITED",
        )

def record(key: str) -> None:
    _attempts[key].append(monotonic())

def clear(key: str) -> None:
    _attempts.pop(key, None)
```

Key on both the client address and the submitted Employee ID, check before
verifying, record on every failure, clear on success. In-memory is honest for a
single process; behind more than one worker it needs Redis, and that swap is the
only thing that changes.

### Fix 7, concretely

Add `token_version INTEGER NOT NULL DEFAULT 0` to `employees`, put it in the JWT
as `tv`, compare it in `get_current_employee`, and increment it in
`set_password` and in a new "sign out everywhere" action. Three lines in each
place, and it turns logout and password change into real revocation.
