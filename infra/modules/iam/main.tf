# IAM module — one instance profile per host ROLE. An instance profile lets an
# EC2 box assume an IAM role and carry its permissions as an identity, so hosts
# never store long-lived AWS keys. Two roles:
#   sentinel-worker  (app-1, app-2, db-1, mon-1) : read /sentinel/* secrets only
#   sentinel-ctrl    (ctrl-1)                     : + Bedrock invoke + EC2 start/stop
#
# No wildcard resources except ec2:DescribeInstances, which AWS does not support
# resource-level permissions for (read-only, so acceptable).

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  ssm_params_arn = "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/sentinel/*"
  bedrock_models = "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/*"
}

# EC2 service may assume these roles.
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# Shared: read + decrypt /sentinel/* secrets.
data "aws_iam_policy_document" "ssm_read" {
  statement {
    sid       = "ReadSentinelParams"
    actions   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    resources = [local.ssm_params_arn]
  }
  statement {
    sid       = "DecryptSecrets"
    actions   = ["kms:Decrypt"]
    resources = [var.secrets_kms_key_arn]
  }
}

# ===== Worker role: SSM read only =====
resource "aws_iam_role" "worker" {
  name               = "sentinel-worker"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy" "worker_ssm" {
  name   = "ssm-read"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.ssm_read.json
}

resource "aws_iam_instance_profile" "worker" {
  name = "sentinel-worker"
  role = aws_iam_role.worker.name
}

# ===== Control role: SSM read + Bedrock + EC2 start/stop =====
data "aws_iam_policy_document" "ctrl_extra" {
  statement {
    sid       = "InvokeBedrock"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [local.bedrock_models]
  }
  statement {
    sid       = "DescribeInstances"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"] # DescribeInstances has no resource-level permissions
  }
  statement {
    sid       = "StartStopSentinelOnly"
    actions   = ["ec2:StartInstances", "ec2:StopInstances"]
    resources = ["arn:aws:ec2:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:instance/*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/Project"
      values   = ["sentinel"]
    }
  }
}

resource "aws_iam_role" "ctrl" {
  name               = "sentinel-ctrl"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy" "ctrl_ssm" {
  name   = "ssm-read"
  role   = aws_iam_role.ctrl.id
  policy = data.aws_iam_policy_document.ssm_read.json
}

resource "aws_iam_role_policy" "ctrl_extra" {
  name   = "bedrock-ec2"
  role   = aws_iam_role.ctrl.id
  policy = data.aws_iam_policy_document.ctrl_extra.json
}

resource "aws_iam_instance_profile" "ctrl" {
  name = "sentinel-ctrl"
  role = aws_iam_role.ctrl.name
}
