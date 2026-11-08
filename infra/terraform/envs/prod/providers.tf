terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
}

provider "aws" {
  region = var.region

  # PLACEHOLDER: CI assumes the per-env deploy role via GitHub OIDC; humans use IAM Identity Center.
  # assume_role { role_arn = "arn:aws:iam::<account-id>:role/td-terraform-<env>" }

  default_tags {
    tags = {
      Project     = "techdrona-lms"
      Environment = var.env
      ManagedBy   = "terraform"
      Profile     = var.sizing_profile
    }
  }
}

# Global control plane only (CloudFront ACM certificate, WAF CLOUDFRONT scope). No data here.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "techdrona-lms"
      Environment = var.env
      ManagedBy   = "terraform"
    }
  }
}
