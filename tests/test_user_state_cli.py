from __future__ import annotations

import json
from pathlib import Path

import scripts.user_state as user_state_cli


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_user_state_cli_add_list_export(tmp_path: Path, monkeypatch, capsys) -> None:
    user_state_dir = tmp_path / "state" / "user_state"
    monkeypatch.setattr(user_state_cli, "USER_STATE_DIR", user_state_dir)

    rc = user_state_cli.main(
        [
            "add-status",
            "--profile",
            "cs",
            "--job-id",
            "job-1",
            "--status",
            "saved",
            "--notes",
            "tracking",
        ]
    )
    assert rc == 0
    payload = _read(user_state_dir / "cs.json")
    assert payload["schema_version"] == 1
    assert payload["jobs"]["job-1"]["status"] == "saved"
    capsys.readouterr()

    rc = user_state_cli.main(["list", "--profile", "cs", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    listed = json.loads(out)
    assert listed["jobs"]["job-1"]["status"] == "saved"

    export_path = tmp_path / "exported.json"
    rc = user_state_cli.main(["export", "--profile", "cs", "--out", str(export_path)])
    assert rc == 0
    exported = _read(export_path)
    assert exported == payload
