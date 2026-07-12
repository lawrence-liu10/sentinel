# Bootstrap stack — applied ONCE with local state. It stands up:
#   1. A monthly cost budget + email alerts (the first cost guardrail).
#   2. An S3 bucket for the main stack's remote Terraform state.
#   3. A DynamoDB table that locks that state during applies.
# After `terraform apply` here, copy the state_bucket output into ../backend.tf
# and run `terraform init` in ../ to point the main stack at this backend.

data "aws_caller_identity" "current" {}

locals {
  # Bucket names are globally unique, so we suffix with the account id.
  state_bucket = "sentinel-tfstate-${data.aws_caller_identity.current.account_id}"
}

# --- Cost guardrail: $25/mo budget, email at 20/50/80/100% of the limit ---
# 20% of $25 = $5, which is the "$5 alarm" the overview calls for.
resource "aws_budgets_budget" "monthly" {
  name         = "sentinel-monthly"
  budget_type  = "COST"
  limit_amount = "25"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = toset([20, 50, 80, 100])
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = ["lawrence.liu10@gmail.com"]
    }
  }
}

# --- Remote state bucket (versioned, encrypted, no public access) ---
resource "aws_s3_bucket" "tfstate" {
  bucket = local.state_bucket
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- State lock table ---
resource "aws_dynamodb_table" "tf_lock" {
  name         = "sentinel-tf-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}

output "state_bucket" {
  value       = aws_s3_bucket.tfstate.id
  description = "Copy this into ../backend.tf, then run `terraform init` in ../"
}

output "lock_table" {
  value       = aws_dynamodb_table.tf_lock.name
  description = "DynamoDB lock table name for the S3 backend."
}
