"""
Tests for Employee ID authentication and employee administration.

These are the tests that matter most in the project, because every other
suite checks a number and these check a boundary. They are written against
the *properties* the requirement asks for rather than the implementation:

* a password is never stored in plain text and never returned,
* a failed sign-in does not reveal whether the Employee ID exists,
* an admin route rejects a non-admin caller at the API, not in the UI,
* an inactive account cannot sign in, and loses access mid-session,
* an Employee ID cannot be duplicated.

The suite runs against its own temporary SQLite file so it never touches the
developer's database, and at a low bcrypt cost so hashing does not dominate
the runtime.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Must be set before `config` is imported anywhere, because Settings reads the
# environment at class-definition time.
_TMP_DIR = tempfile.mkdtemp(prefix="qfleet-test-")
_DB_PATH = Path(_TMP_DIR) / "test_accounts.db"
os.environ["QGF_DATABASE_URL"] = f"sqlite:///{_DB_PATH.as_posix()}"
os.environ["QGF_JWT_SECRET"] = "test-secret-not-used-anywhere-real"
os.environ.setdefault("QGF_BCRYPT_ROUNDS", "4")

from backend.auth import ratelimit, security  # noqa: E402
from backend.auth.service import create_employee  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.db.base import Base  # noqa: E402
from backend.db.models import Employee, Role, normalise_employee_id  # noqa: E402
from backend.db import session as db_session  # noqa: E402

ADMIN_PASSWORD = "Admin@12345"
STAFF_PASSWORD = "Staff@12345"


@pytest.fixture(scope="module", autouse=True)
def _database():
    """A fresh database for this module, torn down afterwards."""
    settings.DATABASE_URL = f"sqlite:///{_DB_PATH.as_posix()}"
    settings.BCRYPT_ROUNDS = 4
    settings.JWT_SECRET = "test-secret-not-used-anywhere-real"
    db_session.reset_engine()

    engine = db_session.get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with db_session.session_scope() as db:
        create_employee(
            db,
            employee_id="EMP001",
            full_name="Fleet Administrator",
            password=ADMIN_PASSWORD,
            role=Role.ADMIN.value,
            department="Operations",
            email="admin@qfleet.local",
        )
        create_employee(
            db,
            employee_id="EMP002",
            full_name="Priya Nair",
            password=STAFF_PASSWORD,
            role=Role.EMPLOYEE.value,
            department="Voyage Planning",
        )
        create_employee(
            db,
            employee_id="EMP099",
            full_name="Revoked Person",
            password=STAFF_PASSWORD,
            role=Role.EMPLOYEE.value,
            department="Bunkering",
            is_active=False,
        )

    yield
    db_session.reset_engine()


def _reset_limiters() -> None:
    """
    Clear every loaded copy of the limiter.

    `main` imports the backend packages bare (`auth.ratelimit`) while the tests
    import them as `backend.auth.ratelimit`, so the same source file is loaded
    twice as two distinct modules with two distinct counters. Resetting only
    the test's copy leaves the one the API actually uses full, which shows up
    as unrelated tests failing with 429.
    """
    import sys

    for name in ("auth.ratelimit", "backend.auth.ratelimit"):
        module = sys.modules.get(name)
        if module is not None:
            module.reset_all()


@pytest.fixture(autouse=True)
def _clean_limiter():
    """
    The limiter is process-global and counts failures. Several tests below
    fail logins on purpose; without this they would lock each other out and
    the suite would pass or fail depending on ordering.
    """
    _reset_limiters()
    yield
    _reset_limiters()


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    import backend.main as main

    with TestClient(main.app) as c:
        yield c


def _token(client, employee_id: str, password: str) -> str:
    response = client.post(
        "/api/auth/login", json={"employee_id": employee_id, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'EMP001', ADMIN_PASSWORD)}"}


@pytest.fixture(scope="module")
def staff_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'EMP002', STAFF_PASSWORD)}"}


# ---------------------------------------------------------------------------
# Password storage
# ---------------------------------------------------------------------------
class TestPasswordHashing:
    def test_hash_is_not_the_password(self):
        digest = security.hash_password("hunter2-hunter2")
        assert digest != "hunter2-hunter2"
        assert "hunter2" not in digest
        assert digest.startswith("$2")  # bcrypt

    def test_same_password_hashes_differently(self):
        """A per-hash salt, so two people with the same password are not visibly equal."""
        assert security.hash_password("same-password") != security.hash_password("same-password")

    def test_verify_round_trip(self):
        digest = security.hash_password("correct-horse-battery")
        assert security.verify_password("correct-horse-battery", digest)
        assert not security.verify_password("Correct-horse-battery", digest)
        assert not security.verify_password("", digest)

    def test_verify_survives_a_corrupt_hash(self):
        """A damaged row must fail to log in, not 500 the endpoint."""
        assert not security.verify_password("anything", "not-a-bcrypt-hash")
        assert not security.verify_password("anything", None)

    def test_overlong_password_is_rejected_not_truncated(self):
        """bcrypt ignores bytes past 72; silently accepting a wrong suffix would be worse."""
        with pytest.raises(ValueError):
            security.hash_password("x" * 200)

    def test_stored_row_holds_no_plain_text(self):
        with db_session.session_scope() as db:
            row = db.query(Employee).filter_by(employee_id="EMP001").one()
            assert ADMIN_PASSWORD not in row.password_hash
            assert row.password_hash.startswith("$2")


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
class TestTokens:
    def test_round_trip(self):
        token, expires_at = security.create_access_token(
            subject="7", employee_id="EMP007", role="EMPLOYEE"
        )
        claims = security.decode_access_token(token)
        assert claims["sub"] == "7"
        assert claims["eid"] == "EMP007"
        assert claims["role"] == "EMPLOYEE"
        assert expires_at is not None

    def test_expired_token_is_rejected(self):
        token, _ = security.create_access_token(
            subject="7", employee_id="EMP007", role="EMPLOYEE", expires_minutes=-1
        )
        with pytest.raises(security.TokenError):
            security.decode_access_token(token)

    def test_tampered_token_is_rejected(self):
        token, _ = security.create_access_token(
            subject="7", employee_id="EMP007", role="ADMIN"
        )
        header, payload, signature = token.split(".")
        forged = f"{header}.{payload}.{signature[:-4]}AAAA"
        with pytest.raises(security.TokenError):
            security.decode_access_token(forged)

    def test_token_signed_with_another_key_is_rejected(self):
        import jwt

        forged = jwt.encode(
            {"sub": "1", "role": "ADMIN", "iat": 0, "exp": 9_999_999_999, "iss": "qfleet"},
            "some-other-secret",
            algorithm="HS256",
        )
        with pytest.raises(security.TokenError):
            security.decode_access_token(forged)


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------
class TestLogin:
    def test_valid_credentials(self, client):
        response = client.post(
            "/api/auth/login", json={"employee_id": "EMP001", "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["employee"]["employee_id"] == "EMP001"
        assert body["employee"]["role"] == "ADMIN"

    def test_employee_id_is_case_insensitive(self, client):
        """"emp001" and "EMP001" are the same person, or the unique index is a lie."""
        response = client.post(
            "/api/auth/login", json={"employee_id": "  emp001 ", "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200
        assert response.json()["employee"]["employee_id"] == "EMP001"

    def test_wrong_password_is_rejected(self, client):
        response = client.post(
            "/api/auth/login", json={"employee_id": "EMP001", "password": "not-the-password"}
        )
        assert response.status_code == 401

    def test_no_account_enumeration(self, client):
        """
        The requirement in one test: an unknown ID and a wrong password must be
        indistinguishable to the client.
        """
        unknown = client.post(
            "/api/auth/login", json={"employee_id": "NOSUCHID", "password": "whatever12"}
        )
        wrong = client.post(
            "/api/auth/login", json={"employee_id": "EMP001", "password": "whatever12"}
        )
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json()
        assert unknown.json()["error"]["message"] == "Invalid Employee ID or password"

    def test_error_never_names_the_employee(self, client):
        response = client.post(
            "/api/auth/login", json={"employee_id": "EMP002", "password": "whatever12"}
        )
        assert "EMP002" not in response.text
        assert "Priya" not in response.text

    def test_inactive_account_cannot_sign_in(self, client):
        response = client.post(
            "/api/auth/login", json={"employee_id": "EMP099", "password": STAFF_PASSWORD}
        )
        assert response.status_code == 401

    def test_inactive_says_so_when_disclosure_is_enabled(self, client, monkeypatch):
        """
        The kinder message is available, just not the default. An operator who
        would rather tell people to call an administrator than leave them
        guessing can turn it on.
        """
        import auth.api as app_auth_api

        monkeypatch.setattr(app_auth_api.settings, "DISCLOSE_INACTIVE", True)
        response = client.post(
            "/api/auth/login", json={"employee_id": "EMP099", "password": STAFF_PASSWORD}
        )
        assert response.status_code == 401
        assert "inactive" in response.json()["error"]["message"].lower()

    def test_missing_fields_are_a_validation_error(self, client):
        assert client.post("/api/auth/login", json={"employee_id": "EMP001"}).status_code == 422
        assert client.post("/api/auth/login", json={"password": "x"}).status_code == 422
        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "", "password": ADMIN_PASSWORD}
            ).status_code
            == 422
        )

    def test_response_never_carries_the_hash(self, client):
        response = client.post(
            "/api/auth/login", json={"employee_id": "EMP001", "password": ADMIN_PASSWORD}
        )
        assert "password_hash" not in response.text
        assert "$2b$" not in response.text


class TestSession:
    def test_me_requires_a_token(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_me_rejects_a_junk_token(self, client):
        response = client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"})
        assert response.status_code == 401

    def test_me_rejects_the_wrong_scheme(self, client):
        response = client.get("/api/auth/me", headers={"Authorization": "Basic abcdef"})
        assert response.status_code == 401

    def test_me_returns_the_signed_in_employee(self, client, staff_headers):
        body = client.get("/api/auth/me", headers=staff_headers).json()
        assert body["employee_id"] == "EMP002"
        assert body["role"] == "EMPLOYEE"
        assert "password_hash" not in body

    def test_logout_needs_a_session(self, client, staff_headers):
        assert client.post("/api/auth/logout").status_code == 401
        assert client.post("/api/auth/logout", headers=staff_headers).status_code == 200

    def test_deactivation_ends_a_live_session(self, client, admin_headers):
        """
        A stateless token cannot be revoked, so access is re-checked against the
        row on every request. Deactivating someone must log them out now, not
        whenever their token happens to expire.
        """
        created = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={
                "employee_id": "EMP300",
                "full_name": "Temporary Contractor",
                "password": "Temp@123456",
                "department": "Chartering",
            },
        ).json()
        headers = {"Authorization": f"Bearer {_token(client, 'EMP300', 'Temp@123456')}"}
        assert client.get("/api/auth/me", headers=headers).status_code == 200

        client.post(f"/api/admin/employees/{created['id']}/deactivate", headers=admin_headers)
        assert client.get("/api/auth/me", headers=headers).status_code == 401


class TestChangeOwnPassword:
    def test_requires_the_current_password(self, client, admin_headers):
        created = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={
                "employee_id": "EMP310",
                "full_name": "Password Changer",
                "password": "First@123456",
            },
        )
        assert created.status_code == 201
        headers = {"Authorization": f"Bearer {_token(client, 'EMP310', 'First@123456')}"}

        wrong = client.post(
            "/api/auth/change-password",
            headers=headers,
            json={"current_password": "nope-nope-nope", "new_password": "Second@123456"},
        )
        assert wrong.status_code == 401

        ok = client.post(
            "/api/auth/change-password",
            headers=headers,
            json={"current_password": "First@123456", "new_password": "Second@123456"},
        )
        assert ok.status_code == 200

        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP310", "password": "First@123456"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP310", "password": "Second@123456"}
            ).status_code
            == 200
        )

    def test_short_password_is_refused(self, client, staff_headers):
        response = client.post(
            "/api/auth/change-password",
            headers=staff_headers,
            json={"current_password": STAFF_PASSWORD, "new_password": "short"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
ADMIN_ROUTES = [
    ("get", "/api/admin/employees", None),
    ("get", "/api/admin/employees/1", None),
    ("post", "/api/admin/employees", {"employee_id": "EMP900", "full_name": "X Y", "password": "Passw0rd!23"}),
    ("put", "/api/admin/employees/1", {"full_name": "Renamed"}),
    ("post", "/api/admin/employees/1/activate", None),
    ("post", "/api/admin/employees/1/deactivate", None),
    ("post", "/api/admin/employees/1/reset-password", {"new_password": "Passw0rd!23"}),
    ("post", "/api/admin/employees/1/revoke-sessions", None),
    ("delete", "/api/admin/employees/1", None),
    ("get", "/api/admin/audit", None),
    ("get", "/api/admin/modules", None),
]


class TestRoleEnforcement:
    """
    Hiding the admin navigation is presentation. These are the checks that
    stop an employee calling the endpoints directly.
    """

    @pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
    def test_anonymous_is_rejected(self, client, method, path, body):
        response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
        assert response.status_code == 401, f"{method.upper()} {path} was reachable without a token"

    @pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
    def test_employee_is_rejected(self, client, staff_headers, method, path, body):
        call = getattr(client, method)
        response = call(path, headers=staff_headers, json=body) if body else call(
            path, headers=staff_headers
        )
        assert response.status_code == 403, f"{method.upper()} {path} let an EMPLOYEE through"

    def test_admin_is_allowed(self, client, admin_headers):
        assert client.get("/api/admin/employees", headers=admin_headers).status_code == 200

    def test_the_router_itself_requires_admin(self):
        """
        The dependency is declared on the router, not route by route, so a
        route added later is protected by construction. This asserts that is
        still how it is wired — moving it onto individual routes would make
        the next one someone adds silently public.
        """
        from backend.admin.api import router

        # Compared by name, not identity: `main` imports the backend packages
        # bare (`admin.api`) while the tests import them as `backend.admin.api`,
        # so the same source file yields two distinct function objects.
        declared = {getattr(dep.dependency, "__name__", "") for dep in router.dependencies}
        assert "require_admin" in declared, "the admin router no longer requires an administrator"

    def test_the_parametrised_cases_cover_every_admin_route(self):
        """
        Guards the two tests above: a new admin endpoint that nobody added to
        ADMIN_ROUTES would otherwise go untested for authorization.
        """
        from backend.admin.api import router

        registered = {
            (method.lower(), route.path)
            for route in router.routes
            for method in route.methods
            if method != "HEAD"
        }
        covered = {(method, path.replace("/1", "/{pk}")) for method, path, _ in ADMIN_ROUTES}
        assert registered - covered == set(), f"untested admin routes: {registered - covered}"


# ---------------------------------------------------------------------------
# Employee management
# ---------------------------------------------------------------------------
class TestEmployeeManagement:
    def test_create_and_sign_in(self, client, admin_headers):
        response = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={
                "employee_id": "emp400",
                "full_name": "  Anand   Kumar ",
                "department": "Bunkering",
                "role": "EMPLOYEE",
                "email": "Anand.Kumar@QFleet.local",
                "password": "harbour-tide-9471",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["employee_id"] == "EMP400"  # normalised
        assert body["full_name"] == "Anand Kumar"  # whitespace collapsed
        assert body["email"] == "anand.kumar@qfleet.local"  # lower-cased
        assert "password" not in body and "password_hash" not in body

        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP400", "password": "harbour-tide-9471"}
            ).status_code
            == 200
        )

    def test_duplicate_employee_id_is_refused(self, client, admin_headers):
        payload = {
            "employee_id": "EMP401",
            "full_name": "First Person",
            "password": "bunker-lane-5520",
        }
        assert client.post("/api/admin/employees", headers=admin_headers, json=payload).status_code == 201
        again = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={**payload, "full_name": "Second Person"},
        )
        assert again.status_code == 409
        assert "already in use" in again.json()["error"]["message"].lower()

    def test_duplicate_is_refused_in_a_different_case(self, client, admin_headers):
        again = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={"employee_id": "emp401", "full_name": "Third Person", "password": "quay-lantern-8813"},
        )
        assert again.status_code == 409

    @pytest.mark.parametrize(
        "payload,field",
        [
            ({"employee_id": "", "full_name": "A B", "password": "Passw0rd!23"}, "employee_id"),
            ({"employee_id": "E", "full_name": "A B", "password": "Passw0rd!23"}, "employee_id"),
            ({"employee_id": "EMP 500", "full_name": "A B", "password": "Passw0rd!23"}, "employee_id"),
            ({"employee_id": "EMP501", "full_name": "", "password": "Passw0rd!23"}, "full_name"),
            ({"employee_id": "EMP502", "full_name": "A B", "password": "short"}, "password"),
            ({"employee_id": "EMP503", "full_name": "A B", "password": "Passw0rd!23", "role": "ROOT"}, "role"),
            (
                {"employee_id": "EMP504", "full_name": "A B", "password": "Passw0rd!23", "email": "nope"},
                "email",
            ),
        ],
    )
    def test_invalid_input_is_rejected(self, client, admin_headers, payload, field):
        response = client.post("/api/admin/employees", headers=admin_headers, json=payload)
        assert response.status_code == 422, f"{field} was accepted: {payload}"

    def test_unknown_field_is_rejected(self, client, admin_headers):
        """`extra="forbid"` — so `{"role": "EMPLOYEE", "is_admin": true}` cannot sneak through."""
        response = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={
                "employee_id": "EMP505",
                "full_name": "A B",
                "password": "Passw0rd!23",
                "password_hash": "$2b$12$injected",
            },
        )
        assert response.status_code == 422

    def test_search_matches_id_name_and_department(self, client, admin_headers):
        by_name = client.get(
            "/api/admin/employees", headers=admin_headers, params={"search": "priya"}
        ).json()
        assert [row["employee_id"] for row in by_name["employees"]] == ["EMP002"]

        by_dept = client.get(
            "/api/admin/employees", headers=admin_headers, params={"search": "voyage"}
        ).json()
        assert "EMP002" in [row["employee_id"] for row in by_dept["employees"]]

        by_id = client.get(
            "/api/admin/employees", headers=admin_headers, params={"search": "emp002"}
        ).json()
        assert by_id["total"] == 1

    def test_list_never_includes_a_hash(self, client, admin_headers):
        response = client.get("/api/admin/employees", headers=admin_headers)
        assert "password_hash" not in response.text
        assert "$2b$" not in response.text

    def test_update_changes_only_what_is_sent(self, client, admin_headers):
        created = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={
                "employee_id": "EMP410",
                "full_name": "Before Rename",
                "department": "Chartering",
                "password": "anchor-drift-3318",
            },
        ).json()

        updated = client.put(
            f"/api/admin/employees/{created['id']}",
            headers=admin_headers,
            json={"full_name": "After Rename"},
        ).json()
        assert updated["full_name"] == "After Rename"
        assert updated["department"] == "Chartering"  # untouched
        assert updated["role"] == "EMPLOYEE"

        # And the password still works: editing a name must not disturb it.
        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP410", "password": "anchor-drift-3318"}
            ).status_code
            == 200
        )

    def test_employee_id_cannot_be_changed_by_update(self, client, admin_headers):
        """It is the login identifier; changing it silently would orphan someone."""
        response = client.put(
            "/api/admin/employees/2", headers=admin_headers, json={"employee_id": "EMP999"}
        )
        assert response.status_code == 422

    def test_deactivate_then_activate(self, client, admin_headers):
        created = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={
                "employee_id": "EMP420",
                "full_name": "On And Off",
                "password": "OnOff@123456",
            },
        ).json()
        pk = created["id"]

        assert client.post(f"/api/admin/employees/{pk}/deactivate", headers=admin_headers).json()[
            "is_active"
        ] is False
        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP420", "password": "OnOff@123456"}
            ).status_code
            == 401
        )

        assert client.post(f"/api/admin/employees/{pk}/activate", headers=admin_headers).json()[
            "is_active"
        ] is True
        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP420", "password": "OnOff@123456"}
            ).status_code
            == 200
        )

    def test_admin_reset_password(self, client, admin_headers):
        created = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={
                "employee_id": "EMP430",
                "full_name": "Forgot Password",
                "password": "Old@12345678",
            },
        ).json()

        response = client.post(
            f"/api/admin/employees/{created['id']}/reset-password",
            headers=admin_headers,
            json={"new_password": "New@12345678"},
        )
        assert response.status_code == 200
        assert "password_hash" not in response.text

        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP430", "password": "Old@12345678"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP430", "password": "New@12345678"}
            ).status_code
            == 200
        )

    def test_delete(self, client, admin_headers):
        created = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={
                "employee_id": "EMP440",
                "full_name": "Short Tenure",
                "password": "jetty-cable-7729",
            },
        ).json()
        assert client.delete(f"/api/admin/employees/{created['id']}", headers=admin_headers).status_code == 200
        assert client.get(f"/api/admin/employees/{created['id']}", headers=admin_headers).status_code == 404

    def test_missing_employee_is_a_404(self, client, admin_headers):
        assert client.get("/api/admin/employees/999999", headers=admin_headers).status_code == 404


class TestLockoutGuards:
    """Nothing may leave the system with no way back into employee management."""

    def test_admin_cannot_deactivate_themselves(self, client, admin_headers):
        me = client.get("/api/auth/me", headers=admin_headers).json()
        response = client.post(f"/api/admin/employees/{me['id']}/deactivate", headers=admin_headers)
        assert response.status_code == 422

    def test_admin_cannot_delete_themselves(self, client, admin_headers):
        me = client.get("/api/auth/me", headers=admin_headers).json()
        assert client.delete(f"/api/admin/employees/{me['id']}", headers=admin_headers).status_code == 422

    def test_admin_cannot_demote_themselves(self, client, admin_headers):
        me = client.get("/api/auth/me", headers=admin_headers).json()
        response = client.put(
            f"/api/admin/employees/{me['id']}", headers=admin_headers, json={"role": "EMPLOYEE"}
        )
        assert response.status_code == 422

    def test_last_active_admin_cannot_be_demoted(self, client, admin_headers):
        """
        Not the same as the self-checks above: this is one admin demoting
        another when they are the only two, then the survivor being the last.
        """
        from backend.auth.service import count_active_admins

        second = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={
                "employee_id": "EMP450",
                "full_name": "Second Admin",
                "password": "estuary-swell-6640",
                "role": "ADMIN",
            },
        ).json()

        second_headers = {"Authorization": f"Bearer {_token(client, 'EMP450', 'estuary-swell-6640')}"}
        me = client.get("/api/auth/me", headers=admin_headers).json()

        # Demote everyone else so EMP450 is the only active administrator.
        for row in client.get("/api/admin/employees", headers=second_headers, params={"role": "ADMIN"}).json()[
            "employees"
        ]:
            if row["id"] != second["id"]:
                client.put(
                    f"/api/admin/employees/{row['id']}",
                    headers=second_headers,
                    json={"role": "EMPLOYEE"},
                )

        with db_session.session_scope() as db:
            assert count_active_admins(db) == 1

        # Now the survivor cannot be demoted by anyone, including themselves.
        blocked = client.put(
            f"/api/admin/employees/{second['id']}", headers=second_headers, json={"role": "EMPLOYEE"}
        )
        assert blocked.status_code == 422

        # Put EMP001 back so later modules are not left admin-less.
        client.put(
            f"/api/admin/employees/{me['id']}", headers=second_headers, json={"role": "ADMIN"}
        )


class TestNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("emp001", "EMP001"),
            ("  EMP001  ", "EMP001"),
            ("emp\t001", "EMP 001"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_employee_id_normalisation(self, raw, expected):
        assert normalise_employee_id(raw) == expected


class TestDataRoutesRequireASession:
    """
    Per-employee module access only means something if the data endpoints
    know who is asking.

    These routes used to answer without a token. That was fine while access
    was uniform, but once an administrator can revoke Fuel Prediction from
    one person, an open ``/api/prediction`` hands it straight back to them
    through curl — the restriction would be a menu that hides a door with no
    lock. ``require_module`` in ``main.py`` closes them, so the guard is real.

    ``/api/health`` stays open on purpose: monitoring and the login screen's
    own status dot both poll it before anyone has signed in, and it exposes
    no fleet data.
    """

    def test_health_is_still_open(self, client):
        assert client.get("/api/health").status_code == 200

    @pytest.mark.parametrize(
        "path",
        [
            "/api/optimization/algorithms",
            "/api/optimization/registry",
            "/api/regulatory/eca-zones",
            "/api/benchmarks/metrics-guide",
            "/api/prediction/metrics",
            "/api/scenarios/fuels",
        ],
    )
    def test_data_routes_refuse_an_anonymous_caller(self, client, path):
        assert client.get(path).status_code == 401

    @pytest.mark.parametrize(
        "path",
        [
            "/api/optimization/algorithms",
            "/api/optimization/registry",
            "/api/regulatory/eca-zones",
            "/api/benchmarks/metrics-guide",
        ],
    )
    def test_an_administrator_still_reaches_everything(self, client, admin_headers, path):
        assert client.get(path, headers=admin_headers).status_code == 200


class TestGrantedScreensActuallyWork:
    """
    The bug this class exists to prevent.

    Module access was first enforced a whole router at a time, which read
    tidily and was wrong: screens share endpoints. The digital twin reads the
    fuel catalogue that nominally belongs to Scenarios; every page with a map
    reads ECA geometry that nominally belongs to Compliance. An employee on
    the default grant opened the Fleet Digital Twin — a screen they were
    explicitly allowed — and got "You do not have access to Scenarios".

    So it is not enough to test that a revoked module is refused. Each of
    these is an endpoint some granted screen calls on load, and a 403 here
    means someone is locked out of a page they were given.
    """

    DEFAULT_SCREEN_CALLS = [
        # catalogue and geometry — several screens draw on each
        "/api/optimization/registry",
        "/api/optimization/algorithms",
        "/api/regulatory/eca-zones",
        "/api/regulatory/seasonality",
        "/api/regulatory/cii-reference",
        "/api/scenarios/fuels",
        # the granted features themselves
        "/api/optimization/fleet?n_vessels=6&n_routes=3",
        "/api/prediction/metrics",
        "/api/prediction/model-info",
    ]

    @pytest.mark.parametrize("path", DEFAULT_SCREEN_CALLS)
    def test_an_employee_on_default_access_can_load_their_screens(
        self, client, staff_headers, path
    ):
        response = client.get(path, headers=staff_headers)
        assert response.status_code == 200, (
            f"{path} returned {response.status_code} to an employee on the default "
            f"grant. Some screen they are allowed to open calls this on load."
        )

    @pytest.mark.parametrize(
        "path",
        ["/api/benchmarks/results", "/api/scenarios/fleet"],
    )
    def test_a_module_they_were_never_granted_is_still_refused(
        self, client, staff_headers, path
    ):
        assert client.get(path, headers=staff_headers).status_code == 403

    def test_revoking_a_module_blocks_its_feature_but_not_the_catalogues(
        self, client, admin_headers, staff_headers
    ):
        """Restricting Fuel Prediction must not take the fuel list with it."""
        staff = client.get("/api/auth/me", headers=staff_headers).json()
        client.put(
            f"/api/admin/employees/{staff['id']}",
            headers=admin_headers,
            json={"permissions": ["dashboard", "simulator", "optimize", "fleet"]},
        ).raise_for_status()
        try:
            assert client.get("/api/prediction/metrics", headers=staff_headers).status_code == 403
            # Still reachable: other granted screens read these.
            assert client.get("/api/scenarios/fuels", headers=staff_headers).status_code == 200
            assert client.get("/api/optimization/registry", headers=staff_headers).status_code == 200
        finally:
            client.put(
                f"/api/admin/employees/{staff['id']}",
                headers=admin_headers,
                json={"permissions": []},
            )


class TestExistingApiIsUntouched:
    """Routes that are open by design and must stay that way."""

    @pytest.mark.parametrize("path", ["/api/health"])
    def test_open_routes_still_answer_without_a_token(self, client, path):
        assert client.get(path).status_code == 200


# ---------------------------------------------------------------------------
# Hardening added after the first security review
# ---------------------------------------------------------------------------
class TestBruteForceProtection:
    """
    The login endpoint was the weakest part of the system: unlimited attempts
    against a 250 ms hash is only a throttle if nobody opens a second
    connection.
    """

    def test_repeated_failures_are_locked_out(self, client):
        limit = settings.LOGIN_MAX_ATTEMPTS_PER_ID
        for _ in range(limit):
            response = client.post(
                "/api/auth/login", json={"employee_id": "EMP001", "password": "wrong-one"}
            )
            assert response.status_code == 401

        blocked = client.post(
            "/api/auth/login", json={"employee_id": "EMP001", "password": "wrong-one"}
        )
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"
        assert blocked.headers.get("Retry-After")

    def test_the_lockout_survives_a_correct_password(self, client):
        """
        Otherwise the limit is pointless: an attacker who guesses right on the
        attempt after the limit still gets in.
        """
        for _ in range(settings.LOGIN_MAX_ATTEMPTS_PER_ID):
            client.post("/api/auth/login", json={"employee_id": "EMP001", "password": "nope"})

        response = client.post(
            "/api/auth/login", json={"employee_id": "EMP001", "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 429

    def test_a_success_clears_the_counter(self, client):
        """Two fat-fingered attempts then the right one must not delay anyone."""
        for _ in range(2):
            client.post("/api/auth/login", json={"employee_id": "EMP001", "password": "nope"})
        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP001", "password": ADMIN_PASSWORD}
            ).status_code
            == 200
        )
        # Counter cleared, so the next wrong guess starts from zero again.
        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP001", "password": "nope"}
            ).status_code
            == 401
        )

    def test_one_account_lockout_does_not_block_another(self, client):
        """Locking EMP001 must not lock the rest of the office out."""
        for _ in range(settings.LOGIN_MAX_ATTEMPTS_PER_ID + 1):
            client.post("/api/auth/login", json={"employee_id": "EMP001", "password": "nope"})
        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP002", "password": STAFF_PASSWORD}
            ).status_code
            == 200
        )

    def test_unknown_ids_are_limited_too(self, client):
        """Otherwise spraying one password across a directory is unlimited."""
        for i in range(settings.LOGIN_MAX_ATTEMPTS_PER_IP + 2):
            response = client.post(
                "/api/auth/login",
                json={"employee_id": f"GHOST{i:04d}", "password": "Spray@12345"},
            )
        assert response.status_code == 429

    def test_the_limiter_runs_before_the_hash(self, client, monkeypatch):
        """
        Ordering matters: checking the limit *after* verifying the password
        would make every blocked request still cost a bcrypt, turning the
        rate limiter into a CPU amplifier.
        """
        calls = []
        real = security.verify_password
        monkeypatch.setattr(
            security, "verify_password", lambda *a, **k: (calls.append(1), real(*a, **k))[1]
        )
        import backend.auth.api as auth_api

        monkeypatch.setattr(auth_api, "verify_password", security.verify_password)

        for _ in range(settings.LOGIN_MAX_ATTEMPTS_PER_ID):
            client.post("/api/auth/login", json={"employee_id": "EMP001", "password": "nope"})
        before = len(calls)
        client.post("/api/auth/login", json={"employee_id": "EMP001", "password": "nope"})
        assert len(calls) == before, "a rate-limited request still hashed a password"


class TestSessionRevocation:
    """`token_version` — what makes a stateless token revocable."""

    def _make(self, client, admin_headers, employee_id, password="Revoke@12345"):
        created = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={"employee_id": employee_id, "full_name": "Revocation Probe", "password": password},
        )
        assert created.status_code == 201, created.text
        return created.json(), {"Authorization": f"Bearer {_token(client, employee_id, password)}"}

    def test_changing_a_password_ends_other_sessions(self, client, admin_headers):
        """
        The message says every other session was signed out. Before this
        existed the message was simply untrue — the old tokens kept working
        until they expired, which is the opposite of what someone changing a
        password after a suspected theft needs.
        """
        _, first = self._make(client, admin_headers, "EMP500")
        second = {"Authorization": f"Bearer {_token(client, 'EMP500', 'Revoke@12345')}"}
        assert client.get("/api/auth/me", headers=second).status_code == 200

        changed = client.post(
            "/api/auth/change-password",
            headers=first,
            json={"current_password": "Revoke@12345", "new_password": "Rotated@98765"},
        )
        assert changed.status_code == 200

        # The other device is out.
        stale = client.get("/api/auth/me", headers=second)
        assert stale.status_code == 401
        assert stale.json()["error"]["code"] == "SESSION_REVOKED"

    def test_the_caller_gets_a_working_token_back(self, client, admin_headers):
        """Being signed out of the device you just used reads as a bug."""
        _, headers = self._make(client, admin_headers, "EMP501")
        changed = client.post(
            "/api/auth/change-password",
            headers=headers,
            json={"current_password": "Revoke@12345", "new_password": "Rotated@98765"},
        )
        fresh = {"Authorization": f"Bearer {changed.json()['access_token']}"}
        assert client.get("/api/auth/me", headers=fresh).status_code == 200

    def test_logout_everywhere_ends_this_session_too(self, client, admin_headers):
        _, headers = self._make(client, admin_headers, "EMP502")
        assert client.post("/api/auth/logout-everywhere", headers=headers).status_code == 200
        assert client.get("/api/auth/me", headers=headers).status_code == 401

    def test_plain_logout_does_not_end_other_sessions(self, client, admin_headers):
        """Signing out of a shared terminal must not kick you off your phone."""
        _, first = self._make(client, admin_headers, "EMP503")
        second = {"Authorization": f"Bearer {_token(client, 'EMP503', 'Revoke@12345')}"}
        assert client.post("/api/auth/logout", headers=first).status_code == 200
        assert client.get("/api/auth/me", headers=second).status_code == 200

    def test_admin_can_revoke_someone_elses_sessions(self, client, admin_headers):
        created, headers = self._make(client, admin_headers, "EMP504")
        assert client.get("/api/auth/me", headers=headers).status_code == 200

        revoked = client.post(
            f"/api/admin/employees/{created['id']}/revoke-sessions", headers=admin_headers
        )
        assert revoked.status_code == 200
        assert client.get("/api/auth/me", headers=headers).status_code == 401

        # The password still works — that is the difference from deactivation.
        assert (
            client.post(
                "/api/auth/login", json={"employee_id": "EMP504", "password": "Revoke@12345"}
            ).status_code
            == 200
        )

    def test_admin_reset_also_revokes(self, client, admin_headers):
        created, headers = self._make(client, admin_headers, "EMP505")
        client.post(
            f"/api/admin/employees/{created['id']}/reset-password",
            headers=admin_headers,
            json={"new_password": "AdminSet@9876"},
        )
        assert client.get("/api/auth/me", headers=headers).status_code == 401

    def test_revoke_sessions_is_admin_only(self, client, staff_headers):
        assert client.post("/api/admin/employees/1/revoke-sessions").status_code == 401
        assert (
            client.post(
                "/api/admin/employees/1/revoke-sessions", headers=staff_headers
            ).status_code
            == 403
        )


class TestPasswordQuality:
    @pytest.mark.parametrize(
        "password,why",
        [
            ("password123", "top of every breach list"),
            ("12345678", "top of every breach list"),
            ("changeme", "top of every breach list"),
            ("aaaabbbb", "too few distinct characters"),
            ("short1", "too short"),
        ],
    )
    def test_weak_passwords_are_refused(self, client, admin_headers, password, why):
        response = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={"employee_id": "EMP600", "full_name": "Weak Password", "password": password},
        )
        assert response.status_code == 422, f"accepted a password that is {why}: {password}"

    def test_password_cannot_be_the_employee_id(self, client, admin_headers):
        """The most common weak password in a staff system, and no generic list catches it."""
        response = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={"employee_id": "EMP601", "full_name": "Self Named", "password": "emp601xyzq"},
        )
        assert response.status_code == 422
        assert "employee id" in response.text.lower()

    def test_password_cannot_contain_the_name(self, client, admin_headers):
        response = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={
                "employee_id": "EMP602",
                "full_name": "Priyanka Sharma",
                "password": "priyanka2026",
            },
        )
        assert response.status_code == 422

    def test_a_reasonable_password_is_accepted(self, client, admin_headers):
        response = client.post(
            "/api/admin/employees",
            headers=admin_headers,
            json={
                "employee_id": "EMP603",
                "full_name": "Sensible Choice",
                "password": "harbour-tide-9471",
            },
        )
        assert response.status_code == 201


class TestSecurityHeaders:
    @pytest.mark.parametrize(
        "header,expected",
        [
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "no-referrer"),
        ],
    )
    def test_headers_are_present(self, client, header, expected):
        assert client.get("/api/health").headers.get(header) == expected

    def test_authenticated_answers_are_not_cached(self, client, admin_headers):
        response = client.get("/api/admin/employees", headers=admin_headers)
        assert response.headers.get("Cache-Control") == "no-store"

    def test_hsts_is_off_by_default(self, client):
        """On plain-http localhost, HSTS pins the origin and is a pain to undo."""
        assert "Strict-Transport-Security" not in client.get("/api/health").headers


class TestInactiveIsPrivateByDefault:
    def test_a_disabled_account_looks_like_a_wrong_password(self, client):
        disabled = client.post(
            "/api/auth/login", json={"employee_id": "EMP099", "password": STAFF_PASSWORD}
        )
        wrong = client.post(
            "/api/auth/login", json={"employee_id": "EMP001", "password": "not-it-either"}
        )
        assert disabled.status_code == wrong.status_code == 401
        assert disabled.json() == wrong.json()


# ---------------------------------------------------------------------------
# Designation, last-login and the audit trail
# ---------------------------------------------------------------------------
class TestProfileFieldsAndAudit:
    """The fields and the log added on top of the core auth boundary."""

    def _make(self, client, admin_headers, employee_id, **extra):
        body = {
            "employee_id": employee_id,
            "full_name": "Test Person",
            "department": "Operations",
            "designation": "Bunker Analyst",
            "role": "EMPLOYEE",
            "password": "harbour-tide-9471",
            **extra,
        }
        response = client.post("/api/admin/employees", headers=admin_headers, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    def test_designation_round_trips(self, client, admin_headers):
        created = self._make(client, admin_headers, "EMP701", designation="Fleet Manager")
        assert created["designation"] == "Fleet Manager"
        fetched = client.get(
            f"/api/admin/employees/{created['id']}", headers=admin_headers
        ).json()
        assert fetched["designation"] == "Fleet Manager"

    def test_designation_can_be_edited(self, client, admin_headers):
        created = self._make(client, admin_headers, "EMP702")
        updated = client.put(
            f"/api/admin/employees/{created['id']}",
            headers=admin_headers,
            json={"designation": "Senior Analyst"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["designation"] == "Senior Analyst"

    def test_new_account_has_never_logged_in(self, client, admin_headers):
        created = self._make(client, admin_headers, "EMP703")
        assert created["last_login"] is None

    def test_login_stamps_last_login(self, client, admin_headers):
        created = self._make(client, admin_headers, "EMP704", password="anchor-drift-3318")
        assert client.post(
            "/api/auth/login", json={"employee_id": "EMP704", "password": "anchor-drift-3318"}
        ).status_code == 200
        after = client.get(
            f"/api/admin/employees/{created['id']}", headers=admin_headers
        ).json()
        assert after["last_login"] is not None

    def test_admin_actions_are_audited(self, client, admin_headers):
        self._make(client, admin_headers, "EMP705")
        entries = client.get("/api/admin/audit", headers=admin_headers).json()["entries"]
        latest = entries[0]
        assert latest["actor"] == "EMP001"
        assert latest["action"] == "Created employee"
        assert latest["target"] == "EMP705"
        assert latest["result"] == "Success"

    def test_audit_never_contains_password_material(self, client, admin_headers):
        created = self._make(client, admin_headers, "EMP706")
        client.post(
            f"/api/admin/employees/{created['id']}/reset-password",
            headers=admin_headers,
            json={"new_password": "bunker-lane-5520"},
        )
        blob = client.get("/api/admin/audit", headers=admin_headers).text
        assert "bunker-lane-5520" not in blob
        assert "password_hash" not in blob

    def test_audit_is_admin_only(self, client, staff_headers):
        assert client.get("/api/admin/audit").status_code == 401
        assert client.get("/api/admin/audit", headers=staff_headers).status_code == 403

    def test_stats_include_inactive(self, client, admin_headers):
        body = client.get("/api/admin/employees", headers=admin_headers).json()
        assert body["inactive"] == body["total"] - body["active"]
