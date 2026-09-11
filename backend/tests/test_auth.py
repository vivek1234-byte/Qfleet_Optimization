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

from backend.auth import security  # noqa: E402
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
    ("delete", "/api/admin/employees/1", None),
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
                "password": "Anand@123456",
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
                "/api/auth/login", json={"employee_id": "EMP400", "password": "Anand@123456"}
            ).status_code
            == 200
        )

    def test_duplicate_employee_id_is_refused(self, client, admin_headers):
        payload = {
            "employee_id": "EMP401",
            "full_name": "First Person",
            "password": "First@123456",
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
            json={"employee_id": "emp401", "full_name": "Third Person", "password": "Third@123456"},
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
                "password": "Before@12345",
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
                "/api/auth/login", json={"employee_id": "EMP410", "password": "Before@12345"}
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
                "password": "Short@123456",
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
                "password": "Second@12345",
                "role": "ADMIN",
            },
        ).json()

        second_headers = {"Authorization": f"Bearer {_token(client, 'EMP450', 'Second@12345')}"}
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


class TestExistingApiIsUntouched:
    """
    Adding accounts must not have put a lock on the optimiser. These routes
    were open before and stay open — see the deliverable note on why.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "/api/health",
            "/api/optimization/algorithms",
            "/api/optimization/registry",
            "/api/regulatory/eca-zones",
            "/api/benchmarks/metrics-guide",
        ],
    )
    def test_open_routes_still_answer_without_a_token(self, client, path):
        assert client.get(path).status_code == 200
