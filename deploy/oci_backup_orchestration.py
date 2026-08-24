"""Verified, fail-closed OCI Object Storage backup orchestration."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import cast
from uuid import UUID

from deploy.snapshot_contract import MANIFEST_ARTIFACTS
from deploy.snapshot_contract import sha256 as calculate_sha256
from deploy.snapshot_verifier import SnapshotVerificationError, verify_snapshot

_BUNDLE_ARTIFACTS = (*MANIFEST_ARTIFACTS, "SHA256SUMS", "COMPLETE")
_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")


class OciBackupError(RuntimeError):
    """Raised when a verified OCI backup cannot be completed safely."""


@dataclass(frozen=True)
class OciBackupConfig:
    namespace: str
    region: str
    bucket: str
    object_name: str


@dataclass(frozen=True)
class UploadReport:
    etag: str


SubprocessRunner = Callable[..., object]


class SubprocessOciUploader:
    """Upload one regular file through the OCI CLI instance-principal flow."""

    def __init__(
        self,
        *,
        runner: SubprocessRunner = subprocess.run,
        timeout_seconds: int = 300,
    ) -> None:
        if timeout_seconds <= 0:
            raise OciBackupError("OCI upload timeout is invalid")
        self._runner = runner
        self._timeout_seconds = timeout_seconds

    async def upload(
        self,
        *,
        path: Path,
        namespace: str,
        region: str,
        bucket: str,
        object_name: str,
        sha256: str,
        auth: str = "instance_principal",
        no_overwrite: bool = True,
        verify_checksum: bool = True,
    ) -> UploadReport:
        _validate_upload_request(
            path=path,
            namespace=namespace,
            region=region,
            bucket=bucket,
            object_name=object_name,
            sha256_digest=sha256,
        )
        if auth != "instance_principal" or not no_overwrite or not verify_checksum:
            raise OciBackupError("OCI upload security options are invalid")

        args = [
            "oci",
            "--auth",
            "instance_principal",
            "--region",
            region,
            "os",
            "object",
            "put",
            "--namespace",
            namespace,
            "--bucket-name",
            bucket,
            "--name",
            object_name,
            "--file",
            str(path),
            "--force",
            "--verify-checksum",
            "--opc-checksum-algorithm",
            "SHA256",
            "--output",
            "json",
        ]
        try:
            current_sha256 = calculate_sha256(path)
        except OSError as error:
            raise OciBackupError("OCI upload payload is invalid") from error
        if current_sha256.casefold() != sha256.casefold():
            raise OciBackupError("OCI upload checksum is invalid")
        try:
            result = await asyncio.to_thread(
                self._runner,
                args,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise OciBackupError("OCI upload timed out") from error
        except Exception as error:
            raise OciBackupError("OCI upload failed") from error

        if getattr(result, "returncode", None) != 0:
            raise OciBackupError("OCI upload failed")
        try:
            response = json.loads(cast(str, getattr(result, "stdout", "")))
            etag = response["etag"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise OciBackupError("OCI upload response is invalid") from error
        if not isinstance(etag, str) or not etag:
            raise OciBackupError("OCI upload response is invalid")
        return UploadReport(etag=etag)


def make_backup_object_name(when: datetime, backup_id: UUID) -> str:
    """Return the portable, date-partitioned key for one immutable backup."""
    utc_when = when.astimezone(UTC)
    return (
        f"backups/zb/{utc_when:%Y/%m/%d}/{backup_id}/snapshot.tar"
    )


def create_verified_bundle(
    *,
    snapshot_dir: Path,
    output_dir: Path,
    object_name: str,
) -> Path:
    """Verify a snapshot then package exactly its tracked contract artifacts."""
    _validate_object_name(object_name)
    try:
        verify_snapshot(snapshot_dir)
    except SnapshotVerificationError as error:
        raise OciBackupError("snapshot is not verified") from error

    bundle_path = output_dir / _bundle_filename(object_name)
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
        with tarfile.open(bundle_path, "w") as archive:
            for artifact_name in _BUNDLE_ARTIFACTS:
                source_path = snapshot_dir.joinpath(*PurePosixPath(artifact_name).parts)
                if not _is_regular_snapshot_artifact(snapshot_dir, source_path):
                    raise OciBackupError("snapshot artifact is unsafe")
                tar_info = archive.gettarinfo(str(source_path), arcname=artifact_name)
                if not tar_info.isreg():
                    raise OciBackupError("snapshot artifact is unsafe")
                tar_info.mtime = 0
                tar_info.uid = 0
                tar_info.gid = 0
                tar_info.uname = ""
                tar_info.gname = ""
                with source_path.open("rb") as source_file:
                    archive.addfile(tar_info, source_file)
    except OciBackupError:
        raise
    except (OSError, tarfile.TarError) as error:
        raise OciBackupError("could not create verified backup bundle") from error
    return bundle_path


def _validate_config(config: OciBackupConfig) -> None:
    _validate_nonempty("OCI namespace", config.namespace)
    _validate_nonempty("OCI region", config.region)
    _validate_nonempty("OCI bucket", config.bucket)
    _validate_object_name(config.object_name)


def _validate_upload_request(
    *,
    path: Path,
    namespace: str,
    region: str,
    bucket: str,
    object_name: str,
    sha256_digest: str,
) -> None:
    _validate_config(
        OciBackupConfig(
            namespace=namespace,
            region=region,
            bucket=bucket,
            object_name=object_name,
        )
    )
    if path.is_symlink() or not path.is_file():
        raise OciBackupError("OCI upload payload is invalid")
    if not _SHA256_PATTERN.fullmatch(sha256_digest):
        raise OciBackupError("OCI upload checksum is invalid")


def _validate_nonempty(label: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise OciBackupError(f"{label} is invalid")


def _validate_object_name(object_name: str) -> None:
    _validate_nonempty("OCI object name", object_name)
    path = PurePosixPath(object_name)
    if (
        "\\" in object_name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in object_name.split("/"))
    ):
        raise OciBackupError("OCI object name is invalid")


def _bundle_filename(object_name: str) -> str:
    filename = object_name.replace("/", "-")
    if not filename or filename in {".", ".."}:
        raise OciBackupError("OCI object name is invalid")
    return filename


def _is_regular_snapshot_artifact(snapshot_dir: Path, artifact_path: Path) -> bool:
    current_path = snapshot_dir
    if current_path.is_symlink():
        return False
    for part in artifact_path.relative_to(snapshot_dir).parts:
        current_path = current_path / part
        if current_path.is_symlink():
            return False
    return artifact_path.is_file()
