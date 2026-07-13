# Outputs for the main stack.

output "vpc_id" {
  description = "Sentinel VPC id."
  value       = module.network.vpc_id
}

output "public_subnet_ids" {
  description = "Public subnet ids, in AZ order."
  value       = module.network.public_subnet_ids
}

# Consumed by scripts/gen-inventory.sh to render the Ansible inventory.
output "hosts" {
  description = "Per-host role + public/private IPs for the generated inventory."
  value       = module.compute.hosts
}

output "ssh_key_path" {
  description = "Local path to the generated SSH private key."
  value       = module.compute.ssh_key_path
}
