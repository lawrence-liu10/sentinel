output "secrets_kms_key_arn" {
  description = "ARN of the KMS key encrypting /sentinel/* secrets; the IAM module scopes kms:Decrypt to exactly this key."
  value       = aws_kms_key.secrets.arn
}

output "secrets_kms_key_id" {
  description = "Key id of the secrets KMS key; the compute module uses it to encrypt the generated SSH private key in SSM."
  value       = aws_kms_key.secrets.key_id
}
