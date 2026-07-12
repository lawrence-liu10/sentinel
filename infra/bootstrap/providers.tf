terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # The bootstrap stack keeps its state LOCAL on purpose: it creates the very
  # S3 bucket + DynamoDB lock table that the main stack's remote backend uses,
  # so its own state can't live there (chicken-and-egg). Never migrate this
  # stack to the S3 backend.
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project = "sentinel"
    }
  }
}
