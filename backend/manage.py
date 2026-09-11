"""
Account administration from the command line.

Everything the admin dashboard can do, plus the two things it cannot: create
the *first* administrator (nobody is signed in yet) and recover from a lost
admin password. Run from the project root:

    python -m backend.manage bootstrap          # create the first admin
    python -m backend.manage seed               # demo employees for a run-through
    python -m backend.manage list
    python -m backend.manage add EMP007 "Priya Nair" --role EMPLOYEE --department Operations
    python -m backend.manage passwd EMP007
    python -m backend.manage deactivate EMP007
    python -m backend.manage activate EMP007
    python -m backend.manage delete EMP007

Passwords are prompted for, not passed as arguments, so they do not end up in
the shell history or in the process list. ``--password`` exists for scripted
setup and says so.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from sqlalchemy import inspect  # noqa: E402

from config import settings  # noqa: E402
from auth.service import (  # noqa: E402
    count_active_admins,
    create_employee,
    delete_employee,
    get_by_employee_id,
    list_employees,
    revoke_sessions,
    set_password,
    update_employee,
)
from auth.security import password_problem  # noqa: E402
from core.errors import AppError  # noqa: E402
from db.base import Base  # noqa: E402
from db.models import Employee, Role, normalise_employee_id  # noqa: E402
from db.session import get_engine, session_scope  # noqa: E402

# Demo staff for `seed`. Passwords are printed on creation and are meant to be
# changed; this is a walkthrough dataset, not a set of real accounts.
DEMO_EMPLOYEES = [
    # id, name, role, department, designation, email, password
    ("EMP001", "Fleet Administrator", "ADMIN", "Operations", "Fleet Administrator", "admin@qfleet.local", "Admin@12345"),
    ("EMP002", "Priya Nair", "EMPLOYEE", "Voyage Planning", "Voyage Planner", "priya.nair@qfleet.local", "Fleet@12345"),
    ("EMP003", "Arjun Menon", "EMPLOYEE", "Bunkering", "Bunker Analyst", "arjun.menon@qfleet.local", "Fleet@12345"),
    ("EMP004", "Sara Iqbal", "EMPLOYEE", "Compliance", "Compliance Officer", "sara.iqbal@qfleet.local", "Fleet@12345"),
    ("EMP005", "Rohit Deshmukh", "ADMIN", "Fleet Management", "Fleet Manager", "rohit.d@qfleet.local", "Admin@12345"),
]


def _die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _require_schema() -> None:
    """Fail with something actionable if migrations have not been run."""
    engine = get_engine()
    if "employees" not in inspect(engine).get_table_names():
        _die(
            "the employees table does not exist.\n"
            "       Run migrations first:  alembic upgrade head\n"
            "       (or, for a throwaway database:  python -m backend.manage init)"
        )


def _prompt_password(label: str = "Password", *, employee_id: str = "", full_name: str = "") -> str:
    while True:
        first = getpass.getpass(f"{label}: ")
        problem = password_problem(first, employee_id=employee_id, full_name=full_name)
        if problem:
            print(f"  {problem}")
            continue
        if first != getpass.getpass("Confirm: "):
            print("  They do not match. Try again.")
            continue
        return first


def _resolve_password(args, label: str = "Password") -> str:
    if getattr(args, "password", None):
        return args.password
    return _prompt_password(label)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
PLACEHOLDER_SECRET = "CHANGE_ME_GENERATE_A_RANDOM_KEY"


def cmd_env(_args) -> None:
    """
    Make sure ``.env`` exists and carries a real signing key.

    Called by the launchers on every run, not just the first. Doing this in
    Python rather than in batch and shell is not tidiness: generating a key
    and substituting it into a file took a `for /f`, delayed expansion and a
    PowerShell call on Windows and a heredoc on Unix, which is four ways to
    get quoting wrong in two languages for one line of work.

    Idempotent. A key that has already been generated is left alone; only the
    placeholder from ``.env.example`` is replaced, because a placeholder
    published in a public example file is not a secret.
    """
    import secrets

    env_path = PROJECT_ROOT / ".env"
    example_path = PROJECT_ROOT / ".env.example"

    if not env_path.exists():
        if not example_path.exists():
            _die(f"neither .env nor .env.example exists in {PROJECT_ROOT}.")
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env from .env.example.")

    text = env_path.read_text(encoding="utf-8")
    if PLACEHOLDER_SECRET in text:
        env_path.write_text(
            text.replace(PLACEHOLDER_SECRET, secrets.token_urlsafe(48)), encoding="utf-8"
        )
        print("Generated a session signing key in .env.")
    else:
        print(".env is configured.")


def cmd_init(_args) -> None:
    """
    Create the tables directly, without Alembic.

    A convenience for a scratch database. `alembic upgrade head` is the real
    path, because it is the one that can also *upgrade* an existing database.
    """
    Base.metadata.create_all(get_engine())
    print(f"Tables created in {settings.DATABASE_URL.split('://', 1)[0]} database.")


def cmd_bootstrap(args) -> None:
    """Create the first administrator."""
    _require_schema()
    with session_scope() as db:
        existing_admins = count_active_admins(db)
        if existing_admins and not args.force:
            print(
                f"{existing_admins} active administrator(s) already exist. "
                "Use the admin dashboard to add more, or pass --force."
            )
            return

        employee_id = args.employee_id or os.getenv("QGF_ADMIN_EMPLOYEE_ID") or "EMP001"
        full_name = args.name or os.getenv("QGF_ADMIN_NAME") or "Fleet Administrator"
        department = args.department or os.getenv("QGF_ADMIN_DEPARTMENT") or "Operations"
        password = args.password or os.getenv("QGF_ADMIN_PASSWORD") or _prompt_password()

        if get_by_employee_id(db, employee_id) is not None:
            _die(f"{normalise_employee_id(employee_id)} already exists. Use `passwd` to reset it.")

        designation = args.designation or os.getenv("QGF_ADMIN_DESIGNATION") or "Fleet Administrator"
        employee = create_employee(
            db,
            employee_id=employee_id,
            full_name=full_name,
            password=password,
            role=Role.ADMIN.value,
            department=department,
            designation=designation,
            email=args.email,
        )
        print(f"Administrator created: {employee.employee_id} ({employee.full_name})")
        print("Sign in at http://localhost:5173 and change this password.")


def cmd_seed(args) -> None:
    """Insert the demo employees, skipping any that already exist."""
    _require_schema()

    # The demo passwords are printed in this file, in the README and in a
    # public repository. Creating those accounts against a real database would
    # hand anyone who has read the repo an administrator login, so `seed`
    # refuses unless the deployment has declared itself a development one.
    if not settings.DEBUG and not args.force:
        _die(
            "refusing to seed demo accounts outside development.\n"
            "       The seeded passwords are published in this repository.\n"
            "       For a real deployment:  python -m backend.manage bootstrap\n"
            "       To seed anyway:         set QGF_DEBUG=true, or pass --force"
        )
    created, skipped = [], []
    with session_scope() as db:
        for employee_id, name, role, department, designation, email, password in DEMO_EMPLOYEES:
            if get_by_employee_id(db, employee_id) is not None:
                skipped.append(employee_id)
                continue
            create_employee(
                db,
                employee_id=employee_id,
                full_name=name,
                password=password,
                role=role,
                department=department,
                designation=designation,
                email=email,
            )
            created.append((employee_id, role, password))

    if created:
        print("Created:")
        width = max(len(row[0]) for row in created)
        for employee_id, role, password in created:
            print(f"  {employee_id:<{width}}  {role:<8}  password: {password}")
        print("\nThese are demo credentials. Change them before this is anywhere real.")
    if skipped:
        print(f"Already present, left alone: {', '.join(skipped)}")
    if not created and not skipped:  # pragma: no cover - defensive
        print("Nothing to do.")


def cmd_list(args) -> None:
    _require_schema()
    with session_scope() as db:
        rows = list_employees(db, search=args.search or "")
        if not rows:
            print("No employees. Run `python -m backend.manage seed` or `bootstrap`.")
            return
        print(f"{'EMPLOYEE ID':<14}{'NAME':<24}{'ROLE':<10}{'DEPARTMENT':<20}{'STATUS'}")
        print("-" * 76)
        for row in rows:
            status = "active" if row.is_active else "INACTIVE"
            print(
                f"{row.employee_id:<14}{row.full_name[:23]:<24}{row.role:<10}"
                f"{(row.department or '-')[:19]:<20}{status}"
            )
        print(f"\n{len(rows)} employee(s).")


def cmd_add(args) -> None:
    _require_schema()
    password = _resolve_password(args)
    with session_scope() as db:
        employee = create_employee(
            db,
            employee_id=args.employee_id,
            full_name=args.name,
            password=password,
            role=args.role,
            department=args.department or "",
            designation=getattr(args, "designation", "") or "",
            email=args.email,
        )
        print(f"Created {employee.employee_id} ({employee.role}).")


def cmd_passwd(args) -> None:
    _require_schema()
    with session_scope() as db:
        employee = _lookup(db, args.employee_id)
        set_password(db, employee, _resolve_password(args, "New password"))
        print(f"Password reset for {employee.employee_id}.")


def cmd_activate(args) -> None:
    _set_active(args.employee_id, True)


def cmd_deactivate(args) -> None:
    _set_active(args.employee_id, False)


def _set_active(employee_id: str, active: bool) -> None:
    _require_schema()
    with session_scope() as db:
        employee = _lookup(db, employee_id)
        update_employee(db, employee, {"is_active": active})
        print(f"{employee.employee_id} is now {'active' if active else 'inactive'}.")


def cmd_role(args) -> None:
    _require_schema()
    with session_scope() as db:
        employee = _lookup(db, args.employee_id)
        update_employee(db, employee, {"role": args.role})
        print(f"{employee.employee_id} is now {args.role}.")


def cmd_revoke(args) -> None:
    _require_schema()
    with session_scope() as db:
        employee = _lookup(db, args.employee_id)
        revoke_sessions(db, employee)
        print(f"{employee.employee_id} has been signed out on every device.")


def cmd_delete(args) -> None:
    _require_schema()
    with session_scope() as db:
        employee = _lookup(db, args.employee_id)
        if not args.yes:
            answer = input(f"Delete {employee.employee_id} ({employee.full_name})? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                print("Cancelled.")
                return
        employee_id = employee.employee_id
        delete_employee(db, employee)
        print(f"{employee_id} deleted.")


def _lookup(db, employee_id: str) -> Employee:
    employee = get_by_employee_id(db, employee_id)
    if employee is None:
        _die(f"no employee with ID {normalise_employee_id(employee_id)}.")
    return employee  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.manage",
        description="QFleet employee accounts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    password_help = "Password (avoid: it lands in your shell history). Prompted for if omitted."

    sub.add_parser(
        "env", help="Create .env if missing and fill in a real signing key"
    ).set_defaults(func=cmd_env)

    sub.add_parser("init", help="Create tables without Alembic (scratch databases only)").set_defaults(
        func=cmd_init
    )

    p = sub.add_parser("bootstrap", help="Create the first administrator")
    p.add_argument("--employee-id", help="Default: EMP001 or QGF_ADMIN_EMPLOYEE_ID")
    p.add_argument("--name", help="Default: Fleet Administrator or QGF_ADMIN_NAME")
    p.add_argument("--department", help="Default: Operations or QGF_ADMIN_DEPARTMENT")
    p.add_argument("--designation", help="Default: Fleet Administrator or QGF_ADMIN_DESIGNATION")
    p.add_argument("--email")
    p.add_argument("--password", help=password_help)
    p.add_argument("--force", action="store_true", help="Create even if an administrator exists")
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("seed", help="Insert demo employees (development only)")
    p.add_argument(
        "--force",
        action="store_true",
        help="Seed even outside development. The passwords are public; be sure.",
    )
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("list", help="List employees")
    p.add_argument("--search", help="Filter by ID, name, department or email")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("add", help="Add an employee")
    p.add_argument("employee_id")
    p.add_argument("name")
    p.add_argument("--role", default=Role.EMPLOYEE.value, choices=Role.values())
    p.add_argument("--department", default="")
    p.add_argument("--designation", default="", help="Job title, e.g. \"Fleet Manager\"")
    p.add_argument("--email")
    p.add_argument("--password", help=password_help)
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("passwd", help="Reset an employee's password")
    p.add_argument("employee_id")
    p.add_argument("--password", help=password_help)
    p.set_defaults(func=cmd_passwd)

    p = sub.add_parser("activate", help="Reactivate an account")
    p.add_argument("employee_id")
    p.set_defaults(func=cmd_activate)

    p = sub.add_parser("deactivate", help="Revoke an account without deleting it")
    p.add_argument("employee_id")
    p.set_defaults(func=cmd_deactivate)

    p = sub.add_parser("role", help="Change an employee's role")
    p.add_argument("employee_id")
    p.add_argument("role", choices=Role.values())
    p.set_defaults(func=cmd_role)

    p = sub.add_parser("revoke", help="Sign an employee out of every device")
    p.add_argument("employee_id")
    p.set_defaults(func=cmd_revoke)

    p = sub.add_parser("delete", help="Delete an employee")
    p.add_argument("employee_id")
    p.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")
    p.set_defaults(func=cmd_delete)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except AppError as exc:
        _die(exc.message)
    except KeyboardInterrupt:  # pragma: no cover
        print("\nCancelled.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
