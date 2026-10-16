# Always-on, near-free pieces: cost alerts and the $15 hard cap, the image
# registry, the GitHub deploy role, and the Daraja sandbox secret. The app stack
# can be destroyed and rebuilt around these without losing images, alerts, or keys.

terraform {
  required_version = ">= 1.10"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # bucket, region, encrypt, and use_lockfile come from ../backend.hcl (see bootstrap).
  backend "s3" {
    key = "foundation.tfstate"
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project = "xmoney-kenya"
      env     = "demo"
      stack   = "foundation"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name = "xmoney-demo"
}
