from __future__ import annotations

from typing import Iterable


def build_container_secrets(entries: Iterable[tuple[str, str]]) -> list[dict[str, str]]:
    secrets: list[dict[str, str]] = []
    for name, value_from in entries:
        name_clean = str(name).strip()
        value_clean = str(value_from).strip()
        if not name_clean or not value_clean:
            continue
        secrets.append({"name": name_clean, "valueFrom": value_clean})
    secrets.sort(key=lambda item: item["name"])
    return secrets


__all__ = ["build_container_secrets"]
