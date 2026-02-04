from __future__ import annotations

from scripts import preflight_env


def test_preflight_run_mode_no_required(monkeypatch, capsys) -> None:
    monkeypatch.delenv("JOBINTEL_S3_BUCKET", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("JOBINTEL_AWS_REGION", raising=False)
    monkeypatch.delenv("AI_ENABLED", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    code = preflight_env.main(["--mode", "run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "MODE: run" in out
    assert "REQUIRED" in out


def test_preflight_publish_missing_bucket(monkeypatch, capsys) -> None:
    for name in [
        "JOBINTEL_S3_BUCKET",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "JOBINTEL_AWS_REGION",
    ]:
        monkeypatch.delenv(name, raising=False)

    code = preflight_env.main(["--mode", "publish"])
    assert code == 2
    err = capsys.readouterr().err
    assert "JOBINTEL_S3_BUCKET" in err


def test_preflight_ai_requires_key(monkeypatch, capsys) -> None:
    monkeypatch.setenv("AI_ENABLED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    code = preflight_env.main(["--mode", "run"])
    assert code == 2
    err = capsys.readouterr().err
    assert "OPENAI_API_KEY" in err

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    code = preflight_env.main(["--mode", "run"])
    assert code == 0
