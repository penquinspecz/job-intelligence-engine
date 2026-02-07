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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def _decrypt_file(src: Path, dst: Path, *, passphrase: str) -> None:
    env = os.environ.copy()
    env["JOBINTEL_BACKUP_PASSPHRASE_VALUE"] = passphrase
    _run_checked(
        [
            "openssl",
            "enc",
            "-d",
            "-aes-256-cbc",
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Restore rehearsal from encrypted S3 backup and verify contents.")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--backup-uri", required=True)
    ap.add_argument("--restore-dir", required=True)
    ap.add_argument("--bundle-root", default="ops/proof/bundles")
    ap.add_argument("--passphrase-env", default="JOBINTEL_BACKUP_PASSPHRASE")
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", ""))
    args = ap.parse_args(argv)

    passphrase = os.environ.get(args.passphrase_env, "")
    if not passphrase:
        print(f"Missing passphrase in env var {args.passphrase_env}", file=sys.stderr)
        return 2

    try:
        bucket, prefix = _parse_s3_uri(args.backup_uri)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    bundle_dir = (REPO_ROOT / args.bundle_root / f"m4-{args.run_id}").resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)
    restore_log = bundle_dir / "restore.log"
    verify_log = bundle_dir / "restore_verify.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line)
        with restore_log.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    client = boto3.client("s3", region_name=args.region or None)
    restore_dir = Path(args.restore_dir).resolve()
    if restore_dir.exists():
        shutil.rmtree(restore_dir)
    restore_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"jobintel-m4-restore-{args.run_id}-") as td:
        tmpdir = Path(td)
        required = ["metadata.json", "checksums.json", "db_backup.enc", "artifacts_backup.enc"]
        for name in required:
            s3_key = f"{prefix}/{name}"
            local = tmpdir / name
            log(f"downloading s3://{bucket}/{s3_key}")
            client.download_file(bucket, s3_key, str(local))

        metadata = json.loads((tmpdir / "metadata.json").read_text(encoding="utf-8"))
        checksums = json.loads((tmpdir / "checksums.json").read_text(encoding="utf-8"))
        verify_lines: list[str] = []
        for name in ("db_backup.enc", "artifacts_backup.enc"):
            got = _sha256_file(tmpdir / name)
            want = str(checksums.get(name, ""))
            ok = got == want
            verify_lines.append(f"sha256 {name}: expected={want} actual={got} ok={ok}")
            if not ok:
                raise RuntimeError(f"checksum mismatch for {name}")

        db_plain = tmpdir / "db_backup.out"
        artifacts_plain = tmpdir / "artifacts_backup.tar.gz"
        _decrypt_file(tmpdir / "db_backup.enc", db_plain, passphrase=passphrase)
        _decrypt_file(tmpdir / "artifacts_backup.enc", artifacts_plain, passphrase=passphrase)

        db_mode = str(metadata.get("db_mode", "unknown"))
        if db_mode == "pg_dump":
            db_target = restore_dir / "db" / "postgres.dump"
            db_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_plain, db_target)
            verify_lines.append(f"db restored: {db_target}")
        else:
            db_target_dir = restore_dir / "db_export"
            db_target_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(db_plain, "r:gz") as tf:
                tf.extractall(path=db_target_dir)
            verify_lines.append(f"db alternative restored: {db_target_dir}")

        with tarfile.open(artifacts_plain, "r:gz") as tf:
            tf.extractall(path=restore_dir)

        state_ok = (restore_dir / "state").exists()
        proof_ok = (restore_dir / "ops" / "proof").exists()
        db_ok = (restore_dir / "db" / "postgres.dump").exists() or (
            restore_dir / "db_export" / "state" / "runs"
        ).exists()
        verify_lines.append(f"verify state_present={state_ok}")
        verify_lines.append(f"verify proof_present={proof_ok}")
        verify_lines.append(f"verify db_present={db_ok}")
        if not (state_ok and proof_ok and db_ok):
            raise RuntimeError("restore verification failed: missing DB or artifact outputs")

        verify_log.write_text("\n".join(verify_lines) + "\n", encoding="utf-8")
        receipt: dict[str, Any] = {
            "schema_version": 1,
            "run_id": args.run_id,
            "backup_uri": args.backup_uri,
            "restore_dir": str(restore_dir),
            "db_mode": db_mode,
            "restore_log": str(restore_log),
            "verify_log": str(verify_log),
            "verified": {
                "state_present": state_ok,
                "proof_present": proof_ok,
                "db_present": db_ok,
            },
        }
        receipt_path = bundle_dir / "restore_receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"restore_receipt={receipt_path}")
        print("restore_status=ok")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
