from __future__ import annotations

import json
from pathlib import Path

from ji_engine.ai.insights_input import build_weekly_insights_input


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_insights_input_builder_is_deterministic(tmp_path: Path) -> None:
    run_dir = tmp_path / "state" / "runs"
    ranked = tmp_path / "ranked.json"
    prev = tmp_path / "prev.json"
    families = tmp_path / "families.json"
    _write_json(
        ranked,
        [
            {"job_id": "a", "title": "Customer Success Manager", "score": 88, "apply_url": "https://example.com/a"},
            {"job_id": "b", "title": "Solutions Architect", "score": 81, "apply_url": "https://example.com/b"},
        ],
    )
    _write_json(
        prev,
        [
            {"job_id": "a", "title": "Customer Success Manager", "score": 87, "apply_url": "https://example.com/a"},
            {"job_id": "c", "title": "Account Executive", "score": 70, "apply_url": "https://example.com/c"},
        ],
    )
    _write_json(
        families,
        [
            {"job_id": "a", "title_family": "customer_success"},
            {"job_id": "b", "title_family": "solutions_engineering"},
            {"job_id": "x", "title_family": "customer_success"},
        ],
    )

    path_one, payload_one = build_weekly_insights_input(
        provider="openai",
        profile="cs",
        ranked_path=ranked,
        prev_path=prev,
        ranked_families_path=families,
        run_id="2026-02-12T00:00:00Z",
        run_metadata_dir=run_dir,
    )
    path_two, payload_two = build_weekly_insights_input(
        provider="openai",
        profile="cs",
        ranked_path=ranked,
        prev_path=prev,
        ranked_families_path=families,
        run_id="2026-02-12T00:00:00Z",
        run_metadata_dir=run_dir,
    )

    p1 = dict(payload_one)
    p2 = dict(payload_two)
    p1.pop("generated_at", None)
    p2.pop("generated_at", None)
    assert p1 == p2
    assert path_one.read_text(encoding="utf-8").splitlines()[0] == "{"
    assert path_one == path_two


def test_insights_input_excludes_raw_jd_text(tmp_path: Path) -> None:
    run_dir = tmp_path / "state" / "runs"
    ranked = tmp_path / "ranked.json"
    _write_json(
        ranked,
        [
            {
                "job_id": "a",
                "title": "Customer Success Manager",
                "score": 88,
                "jd_text": "SECRET_INTERNAL_DESCRIPTION_SHOULD_NOT_APPEAR",
                "description": "raw body that should stay out of insights input payload",
            }
        ],
    )

    out_path, payload = build_weekly_insights_input(
        provider="openai",
        profile="cs",
        ranked_path=ranked,
        prev_path=None,
        ranked_families_path=None,
        run_id="2026-02-12T00:00:00Z",
        run_metadata_dir=run_dir,
    )
    serialized = out_path.read_text(encoding="utf-8")
    assert "SECRET_INTERNAL_DESCRIPTION_SHOULD_NOT_APPEAR" not in serialized
    assert "raw body that should stay out of insights input payload" not in serialized
    assert "jd_text" not in serialized
    assert payload["top_roles"][0]["title"] == "Customer Success Manager"
