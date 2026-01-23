terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  log_group_name = "/ecs/${var.project}"
  task_family    = "${var.project}-daily"
  container_secrets = [
    for item in [
      { name = "OPENAI_API_KEY", valueFrom = var.openai_api_key_ssm_param },
      { name = "DISCORD_WEBHOOK_URL", valueFrom = var.discord_webhook_url_ssm_param }
    ] : item if item.valueFrom != ""
  ]
  ssm_param_inputs = [var.openai_api_key_ssm_param, var.discord_webhook_url_ssm_param]
  ssm_param_arns = [
    for param in local.ssm_param_inputs : (
      param == "" ? null : (
        can(regex("^arn:", param))
        ? param
        : "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${param}"
      )
    )
  ]
  ssm_param_arns_filtered = [for arn in local.ssm_param_arns : arn if arn != null]
  ssm_param_arns_effective = length(local.ssm_param_arns_filtered) > 0 ? local.ssm_param_arns_filtered : [
    "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/jobintel/prod/*"
  ]
}

resource "aws_cloudwatch_log_group" "jobintel" {
  name              = local.log_group_name
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "task_role" {
  name = "${var.project}-task-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role" "events_invoke_role" {
  name = "${var.project}-events-invoke-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "task_policy" {
  name = "${var.project}-task-policy"
  role = aws_iam_role.task_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3Publish"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket}",
          "arn:aws:s3:::${var.s3_bucket}/${var.s3_prefix}/*"
        ]
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.jobintel.arn}:*"
      }
    ]
  })
}

resource "aws_iam_role" "execution_role" {
  name = "${var.project}-execution-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "events_invoke_policy" {
  name = "${var.project}-events-invoke-policy"
  role = aws_iam_role.events_invoke_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RunTask"
        Effect = "Allow"
        Action = [
          "ecs:RunTask"
        ]
        Resource = [
          aws_ecs_task_definition.jobintel.arn
        ]
      },
      {
        Sid    = "PassRole"
        Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = [
          aws_iam_role.execution_role.arn,
          aws_iam_role.task_role.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "execution_role" {
  role       = aws_iam_role.execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_role_ssm" {
  name = "${var.project}-execution-ssm"
  role = aws_iam_role.execution_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      for s in [
        {
          Sid    = "SSMRead"
          Effect = "Allow"
          Action = [
            "ssm:GetParameter",
            "ssm:GetParameters",
            "ssm:GetParametersByPath"
          ]
          Resource = local.ssm_param_arns_effective
        },
        var.ssm_kms_key_arn != "" ? {
          Sid      = "KMSDecrypt"
          Effect   = "Allow"
          Action   = ["kms:Decrypt"]
          Resource = var.ssm_kms_key_arn
        } : null
      ] : s if s != null
    ]
  })
}

resource "aws_ecs_task_definition" "jobintel" {
  family                   = local.task_family
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.execution_role.arn
  task_role_arn            = aws_iam_role.task_role.arn

  container_definitions = jsonencode([
    {
      name       = "jobintel"
      image      = var.container_image
      essential  = true
      entryPoint = ["python", "scripts/run_daily.py"]
      command    = ["--profiles", "cs", "--providers", "openai", "--no_post"]
      secrets    = concat(local.container_secrets, var.container_secrets)
      environment = [
        { name = "JOBINTEL_S3_BUCKET", value = var.s3_bucket },
        { name = "JOBINTEL_S3_PREFIX", value = var.s3_prefix },
        { name = "S3_PUBLISH_ENABLED", value = "1" },
        { name = "S3_PUBLISH_REQUIRE", value = "1" },
        { name = "JOBINTEL_DASHBOARD_URL", value = var.jobintel_dashboard_url }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.jobintel.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = var.project
        }
      }
    }
  ])
}

resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${var.project}-daily"
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "ecs" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = "ecs-task"
  arn       = var.ecs_cluster_arn
  role_arn  = aws_iam_role.events_invoke_role.arn

  ecs_target {
    task_definition_arn = aws_ecs_task_definition.jobintel.arn
    task_count          = 1
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.subnet_ids
      security_groups  = var.security_group_ids
      assign_public_ip = true
    }
  }
}
