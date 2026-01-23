from pathlib import Path

from scripts.aws_bootstrap_prod import parse_csv_list, write_tfvars


def test_parse_csv_list() -> None:
    assert parse_csv_list("a,b , c") == ["a", "b", "c"]
    assert parse_csv_list("") == []


def test_write_tfvars(tmp_path: Path) -> None:
    path = tmp_path / "terraform.tfvars"
    payload = {
        "container_image": "example",
        "subnet_ids": ["subnet-1", "subnet-2"],
    }
    write_tfvars(path, payload)
    content = path.read_text(encoding="utf-8")
    assert "container_image" in content
    assert "subnet_ids" in content
