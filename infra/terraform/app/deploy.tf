# What the GitHub deploy role may do to this stack, scoped to what the stack created.
# It can ship new images and web files; it cannot change networking, IAM, or the
# database. Infrastructure changes are applied by a person with terraform apply.

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "ReadDeployConfig"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.deploy.arn]
  }

  statement {
    sid = "RegisterTaskRevisions"
    actions = [
      "ecs:DescribeTaskDefinition",
      "ecs:RegisterTaskDefinition",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "RollServices"
    actions   = ["ecs:DescribeServices", "ecs:UpdateService"]
    resources = [aws_ecs_service.api.id, aws_ecs_service.worker.id]
  }

  statement {
    sid       = "PassTaskRoles"
    actions   = ["iam:PassRole"]
    resources = concat([for role in aws_iam_role.execution : role.arn], [for role in aws_iam_role.task : role.arn])

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid       = "PointSchedulesAtNewRevisions"
    actions   = ["scheduler:GetSchedule", "scheduler:UpdateSchedule"]
    resources = [for schedule in aws_scheduler_schedule.job : schedule.arn]
  }

  statement {
    sid       = "PassSchedulerRole"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.scheduler.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["scheduler.amazonaws.com"]
    }
  }

  statement {
    sid       = "ListWebBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.web.arn]
  }

  statement {
    sid       = "SyncWebFiles"
    actions   = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.web.arn}/*"]
  }

  statement {
    sid       = "InvalidateCdn"
    actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
    resources = [aws_cloudfront_distribution.web.arn]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy-app-stack"
  role   = data.aws_iam_role.deploy.name
  policy = data.aws_iam_policy_document.deploy.json
}

# Everything the deploy workflow needs to know, so GitHub holds only the role ARN.
resource "aws_ssm_parameter" "deploy" {
  name        = "/${local.name}/deploy"
  description = "Names the GitHub deploy workflow reads."
  type        = "String"
  value = jsonencode({
    cluster         = aws_ecs_cluster.main.name
    api_service     = aws_ecs_service.api.name
    api_family      = aws_ecs_task_definition.api.family
    worker_service  = aws_ecs_service.worker.name
    worker_family   = aws_ecs_task_definition.worker.family
    job_families    = { for name, job in aws_ecs_task_definition.job : name => job.family }
    schedule_group  = aws_scheduler_schedule_group.main.name
    schedules       = keys(aws_scheduler_schedule.job)
    web_bucket      = aws_s3_bucket.web.id
    distribution_id = aws_cloudfront_distribution.web.id
    public_url      = local.public_url
  })
}
