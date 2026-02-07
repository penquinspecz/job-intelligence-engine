from __future__ import annotations

from ji_engine.utils.redaction import scan_json_for_secrets, scan_text_for_secrets


def test_scan_text_for_secrets_detects_known_patterns() -> None:
    text = "\n".join(
        [
            "AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP",
            "Authorization: Bearer token_abcdefghijklmnopqrstuvwxyz12345",
            "https://discord.com/api/webhooks/123456789012345678/abcdEFGHijklMNOP",
            "github_pat_abcdEFGHijklMNOPqrstUVWX1234567890",
            "ghp_abcdefghijklmnopqrstuvwxyzABCDE12345",
            "OPENAI_API_KEY=sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
            "aws_secret_access_key = abcdEFGHijklMNOPqrstUVWXyz0123456789ABCD",
        ]
    )
    findings = scan_text_for_secrets(text)
    patterns = sorted({item.pattern for item in findings})
    assert patterns == [
        "aws_access_key_id",
        "aws_secret_access_key_pair",
        "bearer_token",
        "discord_webhook",
        "github_pat",
        "github_token",
        "openai_api_key",
    ]


def test_scan_text_for_secrets_does_not_flag_random_strings() -> None:
    text = "hash=0123456789abcdef0123456789abcdef01234567 and tokenish value abcdefghijklmnopqrs"
    assert scan_text_for_secrets(text) == []


def test_aws_secret_heuristic_requires_access_key_pairing() -> None:
    text = "aws_secret_access_key=abcdEFGHijklMNOPqrstUVWXyz0123456789ABCD"
    assert scan_text_for_secrets(text) == []


def test_scan_json_for_secrets_reports_deterministic_locations() -> None:
    payload = {
        "provenance": {
            "token": "Bearer token_abcdefghijklmnopqrstuvwxyz12345",
        },
        "items": [
            {"url": "https://discord.com/api/webhooks/123456789012345678/abcdEFGHijklMNOP"},
            {"note": "safe"},
        ],
    }
    findings = scan_json_for_secrets(payload)
    assert [(item.pattern, item.location) for item in findings] == [
        ("discord_webhook", "items[0].url"),
        ("bearer_token", "provenance.token"),
    ]
