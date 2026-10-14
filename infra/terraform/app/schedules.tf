# EventBridge Scheduler starts the two jobs as one-off Fargate Spot tasks. Spot is
# fine here: an interrupted run is simply repeated by the next one.

resource "aws_scheduler_schedule_group" "main" {
  name = local.name
}

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name}-scheduler"
  description        = "EventBridge Scheduler runs the ${local.name} jobs."
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid     = "RunJobTasks"
    actions = ["ecs:RunTask"]
    resources = [
      for job in keys(local.jobs) :
      "arn:${data.aws_partition.current.partition}:ecs:${var.region}:${local.account_id}:task-definition/${local.name}-${job}:*"
    ]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
  }

  statement {
    sid       = "PassJobRoles"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution["jobs"].arn, aws_iam_role.task["jobs"].arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "run-jobs"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

locals {
  schedules = {
    resolve-topups = {
      expression  = var.resolve_topups_schedule
      description = "STK Query top-ups that have had no callback"
      retries     = 0
    }
    demo-reset = {
      expression  = var.demo_reset_schedule
      description = "Wipe the public demo back to its seed"
      retries     = 2
    }
  }
}

resource "aws_scheduler_schedule" "job" {
  for_each = local.schedules

  name                         = each.key
  group_name                   = aws_scheduler_schedule_group.main.name
  description                  = each.value.description
  schedule_expression          = each.value.expression
  schedule_expression_timezone = "Africa/Nairobi"
  state                        = var.awake ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.job[each.key].arn
      task_count          = 1

      capacity_provider_strategy {
        capacity_provider = "FARGATE_SPOT"
        weight            = 1
      }

      network_configuration {
        subnets          = aws_subnet.public[*].id
        security_groups  = [aws_security_group.tasks.id]
        assign_public_ip = true
      }
    }

    retry_policy {
      maximum_retry_attempts       = each.value.retries
      maximum_event_age_in_seconds = 3600
    }
  }

  # Deploys point the schedules at new revisions.
  lifecycle {
    ignore_changes = [target[0].ecs_parameters[0].task_definition_arn]
  }
}
