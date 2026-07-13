# Budget module — the lifetime $100 hard stop.
#
# AWS billing is NOT real-time (cost data refreshes every several hours), so no
# guardrail can kill exactly at $100. We auto-STOP all fleet compute at 90% ($90),
# a deliberate buffer below the $100 credit cap. Stopping halts ~all cost; only
# the ~$5/mo EBS floor remains (run `terraform destroy` to reach a true $0).
#
# include_credit=false makes the budget measure GROSS usage, so it tracks credits
# burned rather than out-of-pocket dollars (which stay ~$0 while credits last).

data "aws_region" "current" {}

# AWS Budgets may assume the stop role on our behalf.
data "aws_iam_policy_document" "budgets_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }
  }
}

# The role may look at any instance but stop only Project=sentinel ones.
data "aws_iam_policy_document" "stop_fleet" {
  statement {
    sid       = "Describe"
    actions   = ["ec2:DescribeInstances", "ec2:DescribeInstanceStatus"]
    resources = ["*"] # Describe* has no resource-level permissions
  }
  statement {
    sid       = "StopSentinelOnly"
    actions   = ["ec2:StopInstances"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/Project"
      values   = ["sentinel"]
    }
  }
}

resource "aws_iam_role" "budget_action" {
  name               = "sentinel-budget-stop"
  assume_role_policy = data.aws_iam_policy_document.budgets_assume.json
}

resource "aws_iam_role_policy" "budget_action" {
  name   = "stop-sentinel-fleet"
  role   = aws_iam_role.budget_action.id
  policy = data.aws_iam_policy_document.stop_fleet.json
}

# Lifetime cap. ANNUALLY (not MONTHLY) so it tracks cumulative usage against the
# one-time $100 credit rather than resetting each month.
resource "aws_budgets_budget" "hard_stop" {
  name         = "sentinel-hard-stop"
  budget_type  = "COST"
  limit_amount = var.hard_stop_limit
  limit_unit   = "USD"
  time_unit    = "ANNUALLY"

  cost_types {
    include_credit = false # measure gross usage = credits burned, not net $
  }

  dynamic "notification" {
    for_each = toset([50, 75, var.action_threshold_percent, 100])
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}

# When gross usage crosses the threshold %, AWS Budgets assumes the role above
# and stops the listed instances via the AWS-StopEC2Instance SSM document.
resource "aws_budgets_budget_action" "stop_fleet" {
  budget_name        = aws_budgets_budget.hard_stop.name
  action_type        = "RUN_SSM_DOCUMENTS"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budget_action.arn

  action_threshold {
    action_threshold_type  = "PERCENTAGE"
    action_threshold_value = var.action_threshold_percent
  }

  definition {
    ssm_action_definition {
      action_sub_type = "STOP_EC2_INSTANCES"
      instance_ids    = var.instance_ids
      region          = data.aws_region.current.name
    }
  }

  subscriber {
    address           = var.alert_email
    subscription_type = "EMAIL"
  }
}
