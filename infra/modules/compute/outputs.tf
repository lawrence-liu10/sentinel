# hosts feeds scripts/gen-inventory.sh, which renders the Ansible inventory.
# Public IPs rotate on stop/start, so this is regenerated on every `make up`.
output "hosts" {
  description = "Per-host role + IPs for the generated Ansible inventory."
  value = {
    for name, inst in aws_instance.host : name => {
      role       = inst.tags["Role"]
      public_ip  = inst.public_ip
      private_ip = inst.private_ip
    }
  }
}

output "ssh_key_path" {
  description = "Local path to the generated SSH private key (chmod 600, gitignored)."
  value       = local_sensitive_file.ssh_private_key.filename
}

# Targets for the budget module's auto-stop action.
output "instance_ids" {
  description = "All fleet instance ids."
  value       = [for name, inst in aws_instance.host : inst.id]
}
