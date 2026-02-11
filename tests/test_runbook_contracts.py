from __future__ import annotations

from pathlib import Path


def test_runbook_contracts_have_required_sections_and_code_blocks() -> None:
    runbooks = sorted(Path("ops").glob("**/RUNBOOK*.md"), key=lambda p: p.as_posix())
    assert runbooks, "No runbooks found under ops/**/RUNBOOK*.md"

    required_headings = ("preflight checks", "success criteria", "if it fails")
    failures: list[str] = []

    for path in runbooks:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        missing = [heading for heading in required_headings if heading not in lowered]
        has_fenced_block = "```" in text

        missing_parts: list[str] = []
        if missing:
            missing_parts.append(f"headings={missing}")
        if not has_fenced_block:
            missing_parts.append("fenced_code_block")

        if missing_parts:
            failures.append(f"{path.as_posix()}: missing {', '.join(missing_parts)}")

    assert not failures, "Runbook contract violations:\n" + "\n".join(sorted(failures))


def test_eks_runbook_requires_nonempty_irsa_arn() -> None:
    path = Path("ops/k8s/RUNBOOK.md")
    text = path.read_text(encoding="utf-8")
    assert ': "${JOBINTEL_IRSA_ROLE_ARN:?' in text
    assert 'JOBINTEL_IRSA_ROLE_ARN="$JOBINTEL_IRSA_ROLE_ARN"' not in text
