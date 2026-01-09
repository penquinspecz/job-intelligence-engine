from pathlib import Path

import scripts.run_daily as run_daily


def _make_job(apply_url: str, title: str, score: int = 1, location: str = "", team: str = "") -> dict:
    return {
        "apply_url": apply_url,
        "title": title,
        "score": score,
        "location": location,
        "team": team,
    }


def test_shortlist_changes_section_appends_sorted_content(tmp_path: Path) -> None:
    """Test basic appending with deterministic sort order (score desc, url asc)."""
    shortlist_path = tmp_path / "shortlist.md"
    shortlist_path.write_text("# Shortlist\n", encoding="utf-8")

    # New jobs: B has higher score, so B should come first
    new_jobs = [
        _make_job("https://example.com/b", "New Role B", score=90),
        _make_job("https://example.com/a", "New Role A", score=85),
    ]
    prev_job_c = _make_job("https://example.com/c", "Old Title", score=80, location="NYC")
    changed_jobs = [
        _make_job("https://example.com/c", "Changed Role", score=85, location="Remote"),
    ]
    removed_jobs = [
        _make_job("https://example.com/e", "Removed Role E", score=50),
        _make_job("https://example.com/d", "Removed Role", score=60),
    ]

    changed_fields = {
        run_daily._job_key(changed_jobs[0]): ["title", "score", "location"],
    }
    prev_jobs = [prev_job_c]

    run_daily._append_shortlist_changes_section(
        shortlist_path,
        profile="cs",
        new_jobs=new_jobs,
        changed_jobs=changed_jobs,
        removed_jobs=removed_jobs,
        prev_exists=True,
        changed_fields=changed_fields,
        prev_jobs=prev_jobs,
        min_alert_score=0,  # No filtering
    )

    lines = shortlist_path.read_text(encoding="utf-8").splitlines()
    start = lines.index("## Changes since last run")

    # New jobs sorted by score desc, then url asc
    assert lines[start + 1] == "### New (2) list items"
    assert lines[start + 2] == "- New Role B — https://example.com/b"  # Score 90
    assert lines[start + 3] == "- New Role A — https://example.com/a"  # Score 85

    # Changed section should include before/after
    changed_idx = lines.index("### Changed (1) list items")
    changed_line = lines[changed_idx + 1]
    assert "Changed Role" in changed_line
    assert "title: Old Title → Changed Role" in changed_line
    assert "score: 80 → 85" in changed_line
    assert "location: NYC → Remote" in changed_line

    # Removed sorted by url asc
    removed_idx = lines.index("### Removed (2) list items")
    assert lines[removed_idx + 1] == "- Removed Role — https://example.com/d"
    assert lines[removed_idx + 2] == "- Removed Role E — https://example.com/e"


def test_shortlist_changes_section_no_prev(tmp_path: Path) -> None:
    """Test behavior when no previous run exists."""
    shortlist_path = tmp_path / "shortlist.md"
    shortlist_path.write_text("# Shortlist\n", encoding="utf-8")

    run_daily._append_shortlist_changes_section(
        shortlist_path,
        profile="cs",
        new_jobs=[],
        changed_jobs=[],
        removed_jobs=[],
        prev_exists=False,
        changed_fields={},
    )

    text = shortlist_path.read_text(encoding="utf-8")
    assert "No previous run to diff against." in text
    assert "### New" not in text


def test_filtering_by_min_alert_score(tmp_path: Path) -> None:
    """Test that new/changed items below min_alert_score are excluded, but removed are always included."""
    shortlist_path = tmp_path / "shortlist.md"
    shortlist_path.write_text("# Shortlist\n", encoding="utf-8")

    new_jobs = [
        _make_job("https://example.com/high", "High Score Job", score=90),
        _make_job("https://example.com/low", "Low Score Job", score=50),
    ]
    changed_jobs = [
        _make_job("https://example.com/changed-high", "Changed High", score=88),
        _make_job("https://example.com/changed-low", "Changed Low", score=40),
    ]
    removed_jobs = [
        _make_job("https://example.com/removed-low", "Removed Low Score", score=30),
        _make_job("https://example.com/removed-high", "Removed High Score", score=95),
    ]

    changed_fields = {
        run_daily._job_key(changed_jobs[0]): ["score"],
        run_daily._job_key(changed_jobs[1]): ["score"],
    }
    prev_jobs = [
        _make_job("https://example.com/changed-high", "Changed High", score=80),
        _make_job("https://example.com/changed-low", "Changed Low", score=45),
    ]

    run_daily._append_shortlist_changes_section(
        shortlist_path,
        profile="cs",
        new_jobs=new_jobs,
        changed_jobs=changed_jobs,
        removed_jobs=removed_jobs,
        prev_exists=True,
        changed_fields=changed_fields,
        prev_jobs=prev_jobs,
        min_alert_score=85,  # Filter threshold
    )

    text = shortlist_path.read_text(encoding="utf-8")

    # New: only high score (1 item shown, but count still shows filtered count)
    assert "### New (1) list items" in text
    assert "High Score Job" in text
    assert "Low Score Job" not in text

    # Changed: only high score
    assert "### Changed (1) list items" in text
    assert "Changed High" in text
    assert "Changed Low" not in text

    # Removed: ALL items regardless of score (2 total)
    assert "### Removed (2) list items" in text
    assert "Removed Low Score" in text
    assert "Removed High Score" in text


def test_before_after_formatting_for_score_and_location() -> None:
    """Test that changed fields show before -> after values."""
    prev_job = _make_job("https://example.com/job", "Old Title", score=80, location="San Francisco", team="Platform")
    curr_job = _make_job("https://example.com/job", "New Title", score=90, location="Remote", team="Core")

    new_jobs: list = []
    changed_jobs = [curr_job]
    removed_jobs: list = []
    changed_fields = {
        run_daily._job_key(curr_job): ["title", "score", "location", "team"],
    }
    prev_map = {run_daily._job_key(prev_job): prev_job}

    result = run_daily.format_changes_section(
        new_jobs=new_jobs,
        changed_jobs=changed_jobs,
        removed_jobs=removed_jobs,
        changed_fields=changed_fields,
        prev_map=prev_map,
        prev_exists=True,
        min_alert_score=0,
    )

    assert "title: Old Title → New Title" in result
    assert "score: 80 → 90" in result
    assert "location: San Francisco → Remote" in result
    assert "team: Platform → Core" in result


def test_description_change_shows_field_name_only() -> None:
    """Test that description changes just say 'description_text' without dumping content."""
    prev_job = _make_job("https://example.com/job", "Job Title", score=80)
    prev_job["description_text"] = "Old description content that is very long"
    curr_job = _make_job("https://example.com/job", "Job Title", score=80)
    curr_job["description_text"] = "New description content that is also very long"

    new_jobs: list = []
    changed_jobs = [curr_job]
    removed_jobs: list = []
    changed_fields = {
        run_daily._job_key(curr_job): ["description"],
    }
    prev_map = {run_daily._job_key(prev_job): prev_job}

    result = run_daily.format_changes_section(
        new_jobs=new_jobs,
        changed_jobs=changed_jobs,
        removed_jobs=removed_jobs,
        changed_fields=changed_fields,
        prev_map=prev_map,
        prev_exists=True,
        min_alert_score=0,
    )

    assert "description_text" in result
    # Should NOT contain the actual description content
    assert "Old description content" not in result
    assert "New description content" not in result


def test_deterministic_ordering_score_desc_url_asc() -> None:
    """Test that items with same score are sorted by URL ascending."""
    # Three jobs with same score - should be sorted by URL
    new_jobs = [
        _make_job("https://example.com/c", "Job C", score=85),
        _make_job("https://example.com/a", "Job A", score=85),
        _make_job("https://example.com/b", "Job B", score=85),
    ]

    result = run_daily.format_changes_section(
        new_jobs=new_jobs,
        changed_jobs=[],
        removed_jobs=[],
        changed_fields={},
        prev_map={},
        prev_exists=True,
        min_alert_score=0,
    )

    lines = result.split("\n")
    new_section_lines = []
    in_new_section = False
    for line in lines:
        if line.startswith("### New"):
            in_new_section = True
            continue
        if line.startswith("### ") and in_new_section:
            break
        if in_new_section and line.startswith("- "):
            new_section_lines.append(line)

    # Should be in URL order: a, b, c
    assert len(new_section_lines) == 3
    assert "Job A" in new_section_lines[0]
    assert "Job B" in new_section_lines[1]
    assert "Job C" in new_section_lines[2]


def test_deterministic_ordering_higher_score_first() -> None:
    """Test that higher score items appear first regardless of URL."""
    new_jobs = [
        _make_job("https://example.com/a", "Low Score", score=70),
        _make_job("https://example.com/z", "High Score", score=95),
        _make_job("https://example.com/m", "Medium Score", score=85),
    ]

    result = run_daily.format_changes_section(
        new_jobs=new_jobs,
        changed_jobs=[],
        removed_jobs=[],
        changed_fields={},
        prev_map={},
        prev_exists=True,
        min_alert_score=0,
    )

    lines = result.split("\n")
    new_section_lines = []
    in_new_section = False
    for line in lines:
        if line.startswith("### New"):
            in_new_section = True
            continue
        if line.startswith("### ") and in_new_section:
            break
        if in_new_section and line.startswith("- "):
            new_section_lines.append(line)

    # Should be in score descending order: High (95), Medium (85), Low (70)
    assert len(new_section_lines) == 3
    assert "High Score" in new_section_lines[0]
    assert "Medium Score" in new_section_lines[1]
    assert "Low Score" in new_section_lines[2]


def test_removed_always_sorted_by_url_asc() -> None:
    """Test that removed items are sorted by URL ascending (regardless of score)."""
    removed_jobs = [
        _make_job("https://example.com/c", "Job C", score=95),
        _make_job("https://example.com/a", "Job A", score=50),
        _make_job("https://example.com/b", "Job B", score=80),
    ]

    result = run_daily.format_changes_section(
        new_jobs=[],
        changed_jobs=[],
        removed_jobs=removed_jobs,
        changed_fields={},
        prev_map={},
        prev_exists=True,
        min_alert_score=0,
    )

    lines = result.split("\n")
    removed_section_lines = []
    in_removed_section = False
    for line in lines:
        if line.startswith("### Removed"):
            in_removed_section = True
            continue
        if line.startswith("### ") and in_removed_section:
            break
        if in_removed_section and line.startswith("- "):
            removed_section_lines.append(line)

    # Should be in URL order: a, b, c (not score order)
    assert len(removed_section_lines) == 3
    assert "Job A" in removed_section_lines[0]
    assert "Job B" in removed_section_lines[1]
    assert "Job C" in removed_section_lines[2]


def test_no_previous_run_behavior() -> None:
    """Test that format_changes_section returns correct message when no previous run."""
    result = run_daily.format_changes_section(
        new_jobs=[_make_job("https://example.com/a", "Job A", score=90)],
        changed_jobs=[],
        removed_jobs=[],
        changed_fields={},
        prev_map={},
        prev_exists=False,
        min_alert_score=0,
    )

    assert "No previous run to diff against." in result
    assert "### New" not in result
    assert "### Changed" not in result
    assert "### Removed" not in result
