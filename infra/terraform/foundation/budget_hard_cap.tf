# Hard cap at $15 actual. This account is the Organizations *management* account
# (Identity Center required it), so an SCP would never apply here. Instead:
# 1) APPLY_IAM_POLICY attaches a deny to the SSO AdministratorAccess role, the
#    GitHub deploy role, and any leftover IAM admin user.
# 2) SNS from the $15 alert invokes a Lambda that scales ECS to 0 and stops RDS.
# IAM deny does not stop already-running ALB/EIP/CloudFront; those keep billing
# until destroyed. RDS that is only stopped will start itself after 7 days.

data "aws_iam_roles" "sso_admin" {
  name_regex  = "AWSReservedSSO_AdministratorAccess_.*"
  path_prefix = "/aws-reserved/sso.amazonaws.com/"
}

data "aws_iam_user" "hard_cap" {
  for_each  = toset(var.budget_cap_iam_users)
  user_name = each.value
}

locals {
  hard_cap_role_names = concat(
    sort(data.aws_iam_roles.sso_admin.names),
    [aws_iam_role.deploy.name],
  )
  hard_cap_role_arns = concat(
    sort(tolist(data.aws_iam_roles.sso_admin.arns)),
    [aws_iam_role.deploy.arn],
  )
  hard_cap_user_names = [for u in data.aws_iam_user.hard_cap : u.user_name]
  hard_cap_user_arns  = [for u in data.aws_iam_user.hard_cap : u.arn]
}

data "aws_iam_policy_document" "hard_cap_deny" {
  statement {
    sid    = "DenyNewBillableResources"
    effect = "Deny"
    actions = [
      "ec2:RunInstances",
      "ec2:StartInstances",
      "ec2:CreateNatGateway",
      "ec2:AllocateAddress",
      "rds:CreateDBInstance",
      "rds:CreateDBCluster",
      "rds:StartDBInstance",
      "rds:StartDBCluster",
      "rds:RestoreDBInstanceFromDBSnapshot",
      "rds:RestoreDBInstanceToPointInTime",
      "ecs:CreateCluster",
      "ecs:CreateService",
      "ecs:UpdateService",
      "ecs:RunTask",
      "ecs:StartTask",
      "elasticloadbalancing:CreateLoadBalancer",
      "elasticloadbalancing:CreateListener",
      "elasticloadbalancing:CreateTargetGroup",
      "cloudfront:CreateDistribution",
      "cloudfront:CreateDistributionWithTags",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "hard_cap_deny" {
  name        = "${local.name}-budget-hard-cap"
  description = "Attached by AWS Budgets at ${var.budget_hard_cap_usd} actual spend. Explicit deny of new billable compute and network."
  policy      = data.aws_iam_policy_document.hard_cap_deny.json
}

data "aws_iam_policy_document" "budgets_actions_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

data "aws_iam_policy_document" "budgets_actions" {
  statement {
    sid = "AttachDenyToRoles"
    actions = [
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
    ]
    resources = local.hard_cap_role_arns

    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = [aws_iam_policy.hard_cap_deny.arn]
    }
  }

  dynamic "statement" {
    for_each = length(local.hard_cap_user_arns) > 0 ? [1] : []

    content {
      sid = "AttachDenyToUsers"
      actions = [
        "iam:AttachUserPolicy",
        "iam:DetachUserPolicy",
      ]
      resources = local.hard_cap_user_arns

      condition {
        test     = "ArnEquals"
        variable = "iam:PolicyARN"
        values   = [aws_iam_policy.hard_cap_deny.arn]
      }
    }
  }
}

resource "aws_iam_role" "budgets_actions" {
  name               = "${local.name}-budgets-actions"
  description        = "Assumed by AWS Budgets to attach the hard-cap deny policy."
  assume_role_policy = data.aws_iam_policy_document.budgets_actions_trust.json
}

resource "aws_iam_role_policy" "budgets_actions" {
  name   = "attach-hard-cap-deny"
  role   = aws_iam_role.budgets_actions.id
  policy = data.aws_iam_policy_document.budgets_actions.json
}

resource "aws_budgets_budget_action" "hard_cap_iam" {
  budget_name        = aws_budgets_budget.monthly.name
  action_type        = "APPLY_IAM_POLICY"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budgets_actions.arn

  action_threshold {
    action_threshold_type  = "ABSOLUTE_VALUE"
    action_threshold_value = var.budget_hard_cap_usd
  }

  definition {
    iam_action_definition {
      policy_arn = aws_iam_policy.hard_cap_deny.arn
      roles      = local.hard_cap_role_names
      users      = length(local.hard_cap_user_names) > 0 ? local.hard_cap_user_names : null
    }
  }

  subscriber {
    address           = var.alert_email
    subscription_type = "EMAIL"
  }

  depends_on = [aws_iam_role_policy.budgets_actions]
}

resource "aws_sns_topic" "hard_cap" {
  name = "${local.name}-budget-hard-cap"
}

data "aws_iam_policy_document" "hard_cap_sns" {
  statement {
    sid     = "AllowBudgetsPublish"
    actions = ["sns:Publish"]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    resources = [aws_sns_topic.hard_cap.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "hard_cap" {
  arn    = aws_sns_topic.hard_cap.arn
  policy = data.aws_iam_policy_document.hard_cap_sns.json
}

data "archive_file" "hard_cap" {
  type        = "zip"
  source_file = "${path.module}/lambda/budget_hard_cap.py"
  output_path = "${path.module}/lambda/budget_hard_cap.zip"
}

resource "aws_cloudwatch_log_group" "hard_cap" {
  name              = "/aws/lambda/${local.name}-budget-hard-cap"
  retention_in_days = 14
}

data "aws_iam_policy_document" "hard_cap_lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "hard_cap_lambda" {
  statement {
    sid = "Logs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.hard_cap.arn}:*"]
  }

  statement {
    sid = "ScaleEcsToZero"
    actions = [
      "ecs:ListClusters",
      "ecs:ListServices",
      "ecs:DescribeServices",
      "ecs:UpdateService",
      "ecs:ListTasks",
      "ecs:StopTask",
    ]
    resources = ["*"]
  }

  statement {
    sid = "StopRds"
    actions = [
      "rds:DescribeDBInstances",
      "rds:StopDBInstance",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role" "hard_cap_lambda" {
  name               = "${local.name}-budget-hard-cap"
  description        = "Scales ECS to 0 and stops RDS when the monthly hard cap is crossed."
  assume_role_policy = data.aws_iam_policy_document.hard_cap_lambda_trust.json
}

resource "aws_iam_role_policy" "hard_cap_lambda" {
  name   = "halt-running-spend"
  role   = aws_iam_role.hard_cap_lambda.id
  policy = data.aws_iam_policy_document.hard_cap_lambda.json
}

resource "aws_lambda_function" "hard_cap" {
  function_name    = "${local.name}-budget-hard-cap"
  description      = "Halt ECS and RDS when actual spend reaches the budget hard cap."
  filename         = data.archive_file.hard_cap.output_path
  source_code_hash = data.archive_file.hard_cap.output_base64sha256
  handler          = "budget_hard_cap.handler"
  runtime          = "python3.12"
  timeout          = 60
  memory_size      = 128
  role             = aws_iam_role.hard_cap_lambda.arn

  depends_on = [
    aws_cloudwatch_log_group.hard_cap,
    aws_iam_role_policy.hard_cap_lambda,
  ]
}

resource "aws_sns_topic_subscription" "hard_cap_lambda" {
  topic_arn = aws_sns_topic.hard_cap.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.hard_cap.arn
}

resource "aws_lambda_permission" "hard_cap_sns" {
  statement_id  = "AllowSnsInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.hard_cap.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.hard_cap.arn
}
