# Inputs for the compute module — subnet + security groups from the network
# module, instance profiles from the iam module, and the secrets KMS key id from
# the ssm module (used to encrypt the generated SSH private key in SSM).

variable "subnet_id" {
  description = "Public subnet all 5 hosts launch into (single AZ to avoid cross-AZ data charges)."
  type        = string
}

variable "sg_app_id" {
  description = "Security group for app-1/app-2."
  type        = string
}

variable "sg_db_id" {
  description = "Security group for db-1."
  type        = string
}

variable "sg_mon_id" {
  description = "Security group for mon-1."
  type        = string
}

variable "sg_ctrl_id" {
  description = "Security group for ctrl-1."
  type        = string
}

variable "ctrl_instance_profile" {
  description = "IAM instance profile name for ctrl-1."
  type        = string
}

variable "worker_instance_profile" {
  description = "IAM instance profile name for app-1/app-2/db-1/mon-1."
  type        = string
}

variable "secrets_kms_key_id" {
  description = "KMS key id used to encrypt /sentinel/ssh_private_key."
  type        = string
}
