from jobintel.aws_secrets import build_container_secrets


def test_build_container_secrets_filters_and_sorts() -> None:
    items = [
        ("DISCORD_WEBHOOK_URL", "arn:aws:ssm:us-east-1:123:parameter/x"),
        ("", "arn:empty"),
        ("OPENAI_API_KEY", "arn:aws:ssm:us-east-1:123:parameter/y"),
        ("OPENAI_API_KEY", ""),
    ]
    secrets = build_container_secrets(items)
    assert secrets == [
        {"name": "DISCORD_WEBHOOK_URL", "valueFrom": "arn:aws:ssm:us-east-1:123:parameter/x"},
        {"name": "OPENAI_API_KEY", "valueFrom": "arn:aws:ssm:us-east-1:123:parameter/y"},
    ]
