# GitHub Actions gets short-lived credentials by OIDC; there are no AWS keys in GitHub.
# The role trusts one repository's jobs in one GitHub environment, so a fork, another
# branch's workflow, or a pull request cannot assume it.

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1

  url = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

data "aws_iam_policy_document" "deploy_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repository}:environment:${var.github_environment}",
        "repo:${var.github_immutable_subject}:environment:${var.github_environment}",
      ]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${local.name}-github-deploy"
  description          = "GitHub Actions deploys of ${var.github_repository} (environment ${var.github_environment})."
  assume_role_policy   = data.aws_iam_policy_document.deploy_trust.json
  max_session_duration = 3600
}

# Pushing images. The app stack attaches the rest (ECS, S3, CloudFront, Scheduler),
# scoped to the resources it creates, and removes it again on destroy.
data "aws_iam_policy_document" "deploy_ecr" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "PushApiImage"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.api.arn]
  }
}

resource "aws_iam_role_policy" "deploy_ecr" {
  name   = "push-api-image"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy_ecr.json
}
