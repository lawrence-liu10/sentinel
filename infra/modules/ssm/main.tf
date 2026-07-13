# SSM module — a customer-managed KMS key + one SecureString placeholder per
# human-entered secret in contracts §10. Terraform creates each parameter with a
# dummy value; the user overwrites the real value once via the AWS CLI.
# ignore_changes = [value] means later applies never revert those hand-entered
# secrets back to the placeholder.
#
# ssh_private_key is intentionally NOT here — the compute module generates the
# key pair and writes /sentinel/ssh_private_key itself (with the real material).
#
# Own KMS key (not the default aws/ssm key) so decrypt can be granted on an exact
# key ARN — least-privilege, no wildcard — and we control rotation + key policy.

resource "aws_kms_key" "secrets" {
  description             = "Encrypts Sentinel SSM SecureString secrets (/sentinel/*)"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = { Name = "sentinel-secrets" }
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/sentinel"
  target_key_id = aws_kms_key.secrets.key_id
}

locals {
  # Human-entered secrets from contracts §10 (ssh_private_key excluded — owned by
  # the compute module).
  secret_names = [
    "anthropic_api_key",
    "slack_bot_token",
    "slack_signing_secret",
    "pg_password",
    "grafana_admin_password",
  ]
}

resource "aws_ssm_parameter" "secret" {
  for_each = toset(local.secret_names)

  name   = "/sentinel/${each.value}"
  type   = "SecureString"
  key_id = aws_kms_key.secrets.key_id
  value  = "PLACEHOLDER" # user overwrites via CLI; ignore_changes keeps it

  lifecycle {
    ignore_changes = [value]
  }

  tags = { Name = "sentinel-${each.value}" }
}
