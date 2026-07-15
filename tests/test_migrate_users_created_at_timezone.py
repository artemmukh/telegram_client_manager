"""Tests for the one-time scripts/migrate_users_created_at_timezone.py script.

Note: this file uses a manually-managed tempfile.TemporaryDirectory()
instead of pytest's built-in tmp_path/tmp_path_factory fixtures. On this
Windows dev machine, pytest's own base temp directory
(%LOCALAPPDATA%/Temp/pytest-of-user) has broken ACLs (a pre-existing,
documented environment issue -- see test_appointment_repository.py /
test_e2e_full_flow.py / test_user_repository.py PermissionErrors), which
makes tmp_path unusable here. tempfile.TemporaryDirectory() creates its
directory elsewhere and is unaffected.
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from scripts.migrate_users_created_at_timezone import migrate_users_created_at


@pytest.fixture
def isolated_cwd():
    """Chdir into a fresh temp directory for the duration of the test.

    cwd is restored before the temp directory is removed -- Windows
    refuses to rmtree a directory that is still the process's current
    working directory.
    """
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.chdir(tmp_dir)
        try:
            yield Path(tmp_dir)
        finally:
            os.chdir(original_cwd)


def _create_users_db(db_path, rows):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT)"
        )
        conn.executemany(
            "INSERT INTO users(created_at) VALUES (?)",
            [(value,) for value in rows],
        )
        conn.commit()
    finally:
        conn.close()


def test_migrate_shifts_existing_created_at_by_five_hours(isolated_cwd):
    db_path = isolated_cwd / "data" / "data_base.db"
    _create_users_db(db_path, ["2026-01-01 10:00:00", "2026-06-15 23:30:00"])

    migrate_users_created_at()

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT created_at FROM users ORDER BY id").fetchall()
    finally:
        conn.close()

    assert rows == [("2026-01-01 15:00:00",), ("2026-06-16 04:30:00",)]


def test_migrate_leaves_null_created_at_rows_untouched(isolated_cwd):
    db_path = isolated_cwd / "data" / "data_base.db"
    # Include one non-NULL row so the function doesn't short-circuit
    # on the "no rows to migrate" early return.
    _create_users_db(db_path, ["2026-01-01 10:00:00", None])

    migrate_users_created_at()

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT created_at FROM users ORDER BY id").fetchall()
    finally:
        conn.close()

    assert rows == [("2026-01-01 15:00:00",), (None,)]


def test_migrate_is_noop_when_database_file_missing(isolated_cwd):
    # data/data_base.db does not exist under this empty isolated cwd.
    migrate_users_created_at()

    assert not (isolated_cwd / "data" / "data_base.db").exists()


def test_migrate_noop_when_no_rows_have_created_at(isolated_cwd):
    db_path = isolated_cwd / "data" / "data_base.db"
    _create_users_db(db_path, [None, None])

    migrate_users_created_at()

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT created_at FROM users ORDER BY id").fetchall()
    finally:
        conn.close()

    assert rows == [(None,), (None,)]


def test_migrate_run_twice_double_shifts_by_design(isolated_cwd):
    """The script is intentionally NOT idempotent (documented in its
    module docstring). This test documents that fact rather than
    guarding against it -- do NOT treat a double-shift here as a bug."""
    db_path = isolated_cwd / "data" / "data_base.db"
    _create_users_db(db_path, ["2026-01-01 10:00:00"])

    migrate_users_created_at()
    migrate_users_created_at()

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT created_at FROM users ORDER BY id").fetchall()
    finally:
        conn.close()

    assert rows == [("2026-01-01 20:00:00",)]
