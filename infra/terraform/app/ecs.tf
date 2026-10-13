# One image, three task definitions: the API service (which also serves the Daraja
# mock), and two scheduled jobs. Each has its own execution role, which reads only
# the secrets that task needs, and its own task role, which has no AWS permissions
# because the code calls no AWS APIs. See docs/adr/007-aws-iam-design.md.

resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}/api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "jobs" {
  name              = "/ecs/${local.name}/jobs"
  retention_in_days = 14
}

# ---- IAM -------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

locals {
  daraja_secret_arns = var.enable_sandbox_rail ? [data.aws_secretsmanager_secret.daraja.arn] : []

  execution_roles = {
    api = {
      log_group = aws_cloudwatch_log_group.api.arn
      secrets   = concat([aws_secretsmanager_secret.db.arn, aws_secretsmanager_secret.app.arn], local.daraja_secret_arns)
    }
    jobs = {
      log_group = aws_cloudwatch_log_group.jobs.arn
      secrets   = concat([aws_secretsmanager_secret.db.arn], local.daraja_secret_arns)
    }
  }
}

resource "aws_iam_role" "execution" {
  for_each = local.execution_roles

  name               = "${local.name}-${each.key}-execution"
  description        = "Starts ${each.key} tasks: pulls the image, writes logs, reads its secrets."
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

data "aws_iam_policy_document" "execution" {
  for_each = local.execution_roles

  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid       = "PullApiImage"
    actions   = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [data.aws_ecr_repository.api.arn]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${each.value.log_group}:*"]
  }

  statement {
    sid       = "ReadOwnSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = each.value.secrets
  }
}

resource "aws_iam_role_policy" "execution" {
  for_each = local.execution_roles

  name   = "start-${each.key}-tasks"
  role   = aws_iam_role.execution[each.key].id
  policy = data.aws_iam_policy_document.execution[each.key].json
}

resource "aws_iam_role" "task" {
  for_each = toset(["api", "jobs"])

  name               = "${local.name}-${each.key}-task"
  description        = "Runtime identity of ${each.key} containers. No permissions: the code calls no AWS APIs."
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

# ---- Container settings -------------------------------------------------------

locals {
  db_env = {
    SANDBOX_MODE = "true"
    DB_HOST      = aws_db_instance.main.address
    DB_PORT      = tostring(aws_db_instance.main.port)
    DB_NAME      = aws_db_instance.main.db_name
    DB_SSLMODE   = "require"
  }

  db_secrets = {
    DB_USERNAME = "${aws_secretsmanager_secret.db.arn}:username::"
    DB_PASSWORD = "${aws_secretsmanager_secret.db.arn}:password::"
  }

  rail_env = {
    PAYMENT_RAILS                 = jsonencode(local.rails)
    DARAJA_SANDBOX_ALLOWED_PHONES = jsonencode(var.sandbox_allowed_phones)
    PUBLIC_BASE_URL               = local.api_url
    STK_QUERY_AFTER_SECONDS       = "60"
    STK_EXPIRE_AFTER_SECONDS      = "300"
  }

  daraja_secrets = var.enable_sandbox_rail ? {
    for key in ["DARAJA_CONSUMER_KEY", "DARAJA_CONSUMER_SECRET", "DARAJA_SHORTCODE", "DARAJA_PASSKEY"] :
    key => "${data.aws_secretsmanager_secret.daraja.arn}:${key}::"
  } : {}

  api_env = merge(local.db_env, local.rail_env, {
    SESSION_COOKIE_SECURE         = "true"
    TRUSTED_PROXY_HOPS            = "2"
    RATE_LIMITS_ENABLED           = "true"
    TOPUP_MAX_CENTS               = tostring(var.topup_max_kes * 100)
    DARAJA_MOCK_CONTROL_ENABLED   = "false"
    DARAJA_MOCK_BASE_URL          = "http://127.0.0.1:8000/sandbox/daraja"
    DARAJA_MOCK_CALLBACK_BASE_URL = "http://127.0.0.1:8000"
  })

  api_secrets = merge(local.db_secrets, local.daraja_secrets, {
    STK_CALLBACK_TOKEN = aws_secretsmanager_secret.app.arn
  })

  # Jobs run outside the API process, so they reach the mock through the public URL.
  resolve_env = merge(local.db_env, local.rail_env, {
    DARAJA_MOCK_BASE_URL = "${local.api_url}/sandbox/daraja"
  })

  jobs = {
    resolve-topups = {
      command = ["xmoney-resolve-topups"]
      env     = local.resolve_env
      secrets = merge(local.db_secrets, local.daraja_secrets)
    }
    demo-reset = {
      command = ["xmoney-demo", "reset", "--yes"]
      env     = merge(local.db_env, { PAYMENT_RAILS = jsonencode(["mock"]) })
      secrets = local.db_secrets
    }
  }
}

# ---- Task definitions -------------------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution["api"].arn
  task_role_arn            = aws_iam_role.task["api"].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "api"
    image     = local.api_image
    essential = true
    portMappings = [{
      containerPort = 8000
      protocol      = "tcp"
    }]
    environment = [for k, v in local.api_env : { name = k, value = v }]
    secrets     = [for k, v in local.api_secrets : { name = k, valueFrom = v }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])

  lifecycle {
    precondition {
      condition     = !var.enable_sandbox_rail || length(var.sandbox_allowed_phones) > 0
      error_message = "The demo is public, so the sandbox rail needs sandbox_allowed_phones."
    }
  }
}

resource "aws_ecs_task_definition" "job" {
  for_each = local.jobs

  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution["jobs"].arn
  task_role_arn            = aws_iam_role.task["jobs"].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name        = "job"
    image       = local.api_image
    essential   = true
    command     = each.value.command
    environment = [for k, v in each.value.env : { name = k, value = v }]
    secrets     = [for k, v in each.value.secrets : { name = k, valueFrom = v }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.jobs.name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.key
      }
    }
  }])
}

# ---- API service ----------------------------------------------------------------

resource "aws_ecs_service" "api" {
  name                              = "api"
  cluster                           = aws_ecs_cluster.main.id
  task_definition                   = aws_ecs_task_definition.api.arn
  desired_count                     = var.awake ? var.api_desired_count : 0
  health_check_grace_period_seconds = 120
  enable_execute_command            = false
  propagate_tags                    = "SERVICE"

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # GitHub Actions registers new revisions with new images; Terraform keeps the
  # settings and leaves the running revision alone.
  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener_rule.from_cloudfront, aws_ecs_cluster_capacity_providers.main]
}
