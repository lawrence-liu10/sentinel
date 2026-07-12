# Remote state backend for the MAIN stack. The bucket + lock table are created
# by the bootstrap stack (../bootstrap) and named sentinel-tfstate-<account-id>.
# CI runs `terraform init -backend=false`, which ignores this block entirely; a
# real `terraform init` here configures the S3 backend and stores state remotely.
terraform {
  backend "s3" {
    bucket         = "sentinel-tfstate-710119225808"
    key            = "main/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "sentinel-tf-lock"
    encrypt        = true
  }
}
