#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import boto3

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ji_engine.utils.time import utc_now, utc_now_z  # noqa: E402


def _utc_compact() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError("backup-uri must start with s3://")
    payload = uri[len("s3://") :]
    if "/" not in payload:
        raise ValueError("backup-uri must include bucket and key prefix")
    bucket, prefix = payload.split("/", 1)
    prefix = prefix.strip("/")
    if not bucket or not prefix:
        raise ValueError("backup-uri bucket/prefix is empty")
    return bucket, prefix


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _run_checked(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(cmd, check=False, text=True, capture_output=True, env=env)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(cmd)}: {detail}")


def _encrypt_file(src: Path, dst: Path, *, passphrase: str) -> None:
    env = os.environ.copy()
    env["JOBINTEL_BACKUP_PASSPHRASE_VALUE"] = passphrase
    _run_checked(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-salt",
            "-pbkdf2",
            "-iter",
            "200000",
            "-in",
            str(src),
            "-out",
            str(dst),
            "-pass",
            "env:JOBINTEL_BACKUP_PASSPHRASE_VALUE",
        ],
        env=env,
    )


def _build_db_backup(tmpdir: Path, *, pg_dsn: str | None) -> tuple[str, Path, str]:
    db_dir = tmpdir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    if pg_dsn and shutil.which("pg_dump"):
        output = db_dir / "postgres.dump"
        _run_checked(["pg_dump", "--format=custom", "--no-owner", "--file", str(output), pg_dsn])
        return "pg_dump", output, "postgres logical dump"

    export = db_dir / "state_runs_export.tar.gz"
    state_runs = REPO_ROOT / "state" / "runs"
    with tarfile.open(export, "w:gz") as tf:
        if state_runs.exists():
            tf.add(state_runs, arcname="state/runs")
    return "state_runs_export", export, "postgres unavailable; backing up run-registry state as database alternative"


def _build_artifacts_backup(tmpdir: Path, *, include_state: Path, include_proof: Path) -> Path:
    output = tmpdir / "artifacts.tar.gz"
    with tarfile.open(output, "w:gz") as tf:
        if include_state.exists():
            tf.add(include_state, arcname="state")
        if include_proof.exists():
            tf.add(include_proof, arcname="ops/proof")
    return output


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Create encrypted on-prem backup and upload to S3 with verification.")
    ap.add_argument("--run-id", default=f"m4-{_utc_compact()}")
    ap.add_argument("--backup-uri", required=True, help="s3://bucket/prefix/backups/<run_id>")
    ap.add_argument("--bundle-root", default="ops/proof/bundles")
    ap.add_argument("--passphrase-env", default="JOBINTEL_BACKUP_PASSPHRASE")
    ap.add_argument("--pg-dsn", default=os.environ.get("JOBINTEL_PG_DSN", ""))
    ap.add_argument("--state-dir", default="state")
    ap.add_argument("--proof-dir", default="ops/proof")
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", ""))
    args = ap.parse_args(argv)

    passphrase = os.environ.get(args.passphrase_env, "")
    if not passphrase:
        print(f"Missing passphrase in env var {args.passphrase_env}", file=sys.stderr)
        return 2

    bundle_dir = (REPO_ROOT / args.bundle_root / f"m4-{args.run_id}").resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)
    backup_log = bundle_dir / "backup.log"
    checksum_log = bundle_dir / "checksum_verify.log"

    def log(msg: str) -> None:
        line = f"{utc_now_z(seconds_precision=True)} {msg}"
        print(line)
        with backup_log.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    try:
        bucket, prefix = _parse_s3_uri(args.backup_uri)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    client = boto3.client("s3", region_name=args.region or None)

    with tempfile.TemporaryDirectory(prefix=f"jobintel-m4-{args.run_id}-") as td:
        tmpdir = Path(td)
        db_mode, db_plain, db_note = _build_db_backup(tmpdir, pg_dsn=args.pg_dsn.strip() or None)
        artifacts_plain = _build_artifacts_backup(
            tmpdir,
            include_state=(REPO_ROOT / args.state_dir),
            include_proof=(REPO_ROOT / args.proof_dir),
        )

        db_enc = tmpdir / "db_backup.enc"
        artifacts_enc = tmpdir / "artifacts_backup.enc"
        _encrypt_file(db_plain, db_enc, passphrase=passphrase)
        _encrypt_file(artifacts_plain, artifacts_enc, passphrase=passphrase)

        checksums = {
            "db_backup.enc": _sha256_file(db_enc),
            "artifacts_backup.enc": _sha256_file(artifacts_enc),
        }
        sizes = {
            "db_backup.enc": db_enc.stat().st_size,
            "artifacts_backup.enc": artifacts_enc.stat().st_size,
        }
        metadata: dict[str, Any] = {
            "schema_version": 1,
            "run_id": args.run_id,
            "timestamp_utc": utc_now_z(seconds_precision=True),
            "backup_uri": args.backup_uri,
            "db_mode": db_mode,
            "db_note": db_note,
            "inputs": {
                "state_dir": str((REPO_ROOT / args.state_dir).resolve()),
                "proof_dir": str((REPO_ROOT / args.proof_dir).resolve()),
            },
            "checksums": checksums,
            "sizes": sizes,
        }

        metadata_path = tmpdir / "metadata.json"
        checksums_path = tmpdir / "checksums.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        checksums_path.write_text(json.dumps(checksums, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        uploads = {
            "metadata.json": metadata_path,
            "checksums.json": checksums_path,
            "db_backup.enc": db_enc,
            "artifacts_backup.enc": artifacts_enc,
        }

        log(f"backup_run_id={args.run_id}")
        log(f"backup_uri={args.backup_uri}")
        log(f"db_mode={db_mode}")
        for key, local_path in uploads.items():
            s3_key = f"{prefix}/{key}"
            log(f"uploading s3://{bucket}/{s3_key}")
            client.upload_file(str(local_path), bucket, s3_key)

        verify_lines: list[str] = []
        for key, local_path in uploads.items():
            s3_key = f"{prefix}/{key}"
            head = client.head_object(Bucket=bucket, Key=s3_key)
            remote_size = int(head.get("ContentLength", -1))
            local_size = local_path.stat().st_size
            ok_size = remote_size == local_size
            verify_lines.append(f"head size {key}: local={local_size} remote={remote_size} ok={ok_size}")
            if not ok_size:
                raise RuntimeError(f"size mismatch for {key}")
            if key.endswith(".enc"):
                downloaded = tmpdir / f"verify-{key}"
                client.download_file(bucket, s3_key, str(downloaded))
                local_sha = _sha256_file(local_path)
                remote_sha = _sha256_file(downloaded)
                ok_sha = local_sha == remote_sha
                verify_lines.append(f"sha256 {key}: local={local_sha} remote={remote_sha} ok={ok_sha}")
                if not ok_sha:
                    raise RuntimeError(f"checksum mismatch for {key}")

        checksum_log.write_text("\n".join(verify_lines) + "\n", encoding="utf-8")
        receipt = {
            "schema_version": 1,
            "run_id": args.run_id,
            "backup_uri": args.backup_uri,
            "bundle_dir": str(bundle_dir),
            "db_mode": db_mode,
            "db_note": db_note,
            "checksums": checksums,
            "sizes": sizes,
            "uploaded_keys": [f"{prefix}/{key}" for key in uploads.keys()],
            "backup_log": str(backup_log),
            "checksum_log": str(checksum_log),
        }
        receipt_path = bundle_dir / "backup_receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"backup_receipt={receipt_path}")
        print("backup_status=ok")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
