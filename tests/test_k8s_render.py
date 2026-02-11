from __future__ import annotations

from pathlib import Path

import pytest

from scripts import k8s_render


def test_eks_overlay_alias_requires_image(monkeypatch) -> None:
    monkeypatch.delenv("JOBINTEL_IMAGE", raising=False)
    with pytest.raises(RuntimeError, match="JOBINTEL_IMAGE is required"):
        k8s_render._render_with_overlays(["eks"])


def test_placeholder_substitution_rejects_empty_env(monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_IRSA_ROLE_ARN", "")
    with pytest.raises(RuntimeError, match="missing env vars"):
        k8s_render._substitute_placeholders(
            "eks.amazonaws.com/role-arn: ${JOBINTEL_IRSA_ROLE_ARN}\n",
            Path("patch-serviceaccount.yaml"),
        )
