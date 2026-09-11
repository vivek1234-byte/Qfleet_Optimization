"""
The accounts database.

This package is the *only* place in the project that knows how to reach a
database. Nothing in ``optimization``, ``prediction``, ``benchmarking``,
``scenario`` or ``regulatory`` touches it — those run entirely on in-memory
data and bundled datasets, and adding accounts did not change that.

Layout:

* ``base`` — the declarative base and naming convention
* ``models`` — the ORM models (currently just ``Employee``)
* ``session`` — engine, session factory and the FastAPI dependency
"""
from .base import Base
from .models import Employee, Role
from .session import get_db, get_engine, get_sessionmaker, session_scope

__all__ = [
    "Base",
    "Employee",
    "Role",
    "get_db",
    "get_engine",
    "get_sessionmaker",
    "session_scope",
]
