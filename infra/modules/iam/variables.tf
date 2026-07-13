variable "secrets_kms_key_arn" {
  description = "ARN of the KMS key encrypting /sentinel/* secrets. Instance roles get kms:Decrypt on exactly this key (needed to read SecureString parameters)."
  type        = string
}
