from scripts.aws_oneoff_run import build_run_task_command, parse_tfvars


def test_parse_tfvars_and_build_command() -> None:
    payload = """
    ecs_cluster_arn = "arn:aws:ecs:us-east-1:123:cluster/jobintel"
    subnet_ids = ["subnet-1","subnet-2"]
    security_group_ids = ["sg-1"]
    aws_region = "us-east-1"
    """
    config = parse_tfvars(payload)
    cmd = build_run_task_command(config)
    assert "arn:aws:ecs:us-east-1:123:cluster/jobintel" in cmd
    assert "subnet-1,subnet-2" in cmd
    assert "sg-1" in cmd
    assert "--region us-east-1" in cmd
