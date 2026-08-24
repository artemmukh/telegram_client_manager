"""SQLite access used exclusively by the VPS snapshot export and verifier."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


class SqliteSnapshotRepositoryError(RuntimeError):
    """Raised when snapshot-specific SQLite access cannot be completed safely."""


@dataclass(frozen=True)
class MedicalRecordFilePath:
    record_id: int
    file_path: str


class SqliteSnapshotRepository:
    """Keep snapshot SQLite reads, writes, and health checks in one boundary."""

    def backup_database(self, source_path: Path, destination_path: Path) -> None:
        try:
            with closing(self._connect_readonly(source_path)) as source, closing(
                sqlite3.connect(destination_path)
            ) as destination:
                source.backup(destination)
                journal_mode = destination.execute("PRAGMA journal_mode = DELETE").fetchone()
                if journal_mode != ("delete",):
                    raise SqliteSnapshotRepositoryError(
                        "could not normalize copied SQLite journal mode"
                    )
        except sqlite3.Error as error:
            raise SqliteSnapshotRepositoryError("could not create SQLite backup") from error

    def assert_healthy(self, database_path: Path) -> None:
        if not database_path.is_file():
            raise SqliteSnapshotRepositoryError("SQLite database is missing")

        try:
            with closing(self._connect_immutable(database_path)) as connection:
                integrity_result = connection.execute("PRAGMA integrity_check").fetchall()
                foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        except sqlite3.Error as error:
            raise SqliteSnapshotRepositoryError("SQLite database health check failed") from error

        if integrity_result != [("ok",)]:
            raise SqliteSnapshotRepositoryError("SQLite integrity check failed")
        if foreign_key_rows:
            raise SqliteSnapshotRepositoryError("SQLite foreign key check failed")

    def list_medical_record_file_paths(
        self,
        database_path: Path,
    ) -> list[MedicalRecordFilePath]:
        try:
            with closing(self._connect_immutable(database_path)) as connection:
                rows = connection.execute(
                    "SELECT id, file_path FROM medical_records WHERE file_path IS NOT NULL"
                ).fetchall()
        except sqlite3.Error as error:
            raise SqliteSnapshotRepositoryError(
                "could not read copied medical record paths"
            ) from error
        return [
            MedicalRecordFilePath(record_id=int(row[0]), file_path=str(row[1]))
            for row in rows
        ]

    def rewrite_medical_record_file_paths(
        self,
        copied_database_path: Path,
        records: Sequence[MedicalRecordFilePath],
    ) -> None:
        try:
            with closing(sqlite3.connect(copied_database_path)) as connection:
                try:
                    connection.execute("PRAGMA foreign_keys = ON")
                    connection.execute("BEGIN IMMEDIATE")
                    connection.executemany(
                        "UPDATE medical_records SET file_path = ? WHERE id = ?",
                        [(record.file_path, record.record_id) for record in records],
                    )
                    connection.commit()
                except sqlite3.Error:
                    connection.rollback()
                    raise
        except sqlite3.Error as error:
            raise SqliteSnapshotRepositoryError(
                "could not rewrite copied medical record paths"
            ) from error

    @staticmethod
    def _connect_readonly(database_path: Path) -> sqlite3.Connection:
        return SqliteSnapshotRepository._connect_with_uri_parameters(
            database_path,
            "mode=ro",
        )

    @staticmethod
    def _connect_immutable(database_path: Path) -> sqlite3.Connection:
        return SqliteSnapshotRepository._connect_with_uri_parameters(
            database_path,
            "mode=ro&immutable=1",
        )

    @staticmethod
    def _connect_with_uri_parameters(
        database_path: Path,
        uri_parameters: str,
    ) -> sqlite3.Connection:
        try:
            resolved_path = database_path.resolve(strict=True)
        except OSError as error:
            raise SqliteSnapshotRepositoryError("SQLite database is missing") from error
        return sqlite3.connect(
            f"{resolved_path.as_uri()}?{uri_parameters}",
            uri=True,
        )
