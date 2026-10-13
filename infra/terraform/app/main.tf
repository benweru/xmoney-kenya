# The destroyable part of the demo: network, database, containers, load balancer,
# CDN, and schedules. `make aws-sleep` scales it to near zero; `make aws-down`
# destroys it (RDS takes a final snapshot first). Foundation stays.

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # bucket, region, encrypt, and use_lockfile come from ../backend.hcl (see bootstrap).
  backend "s3" {
    key = "app.tfstate"
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project = "xmoney-kenya"
      env     = "demo"
      stack   = "app"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# Foundation resources, found by name so the stacks share no state.
data "aws_ecr_repository" "api" {
  name = "${local.name}/api"
}

data "aws_ecr_image" "latest" {
  count = var.api_image_tag == null ? 1 : 0

  repository_name = data.aws_ecr_repository.api.name
  most_recent     = true
}

data "aws_iam_role" "deploy" {
  name = "${local.name}-github-deploy"
}

data "aws_secretsmanager_secret" "daraja" {
  name = "${local.name}/daraja-sandbox"
}

locals {
  name       = "xmoney-demo"
  account_id = data.aws_caller_identity.current.account_id

  public_url = "https://${aws_cloudfront_distribution.web.domain_name}"
  api_url    = "${local.public_url}/api"
  api_image = (var.api_image_tag != null
    ? "${data.aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
    : "${data.aws_ecr_repository.api.repository_url}@${data.aws_ecr_image.latest[0].image_digest}"
  )

  rails = var.enable_sandbox_rail ? ["mock", "sandbox"] : ["mock"]
}
