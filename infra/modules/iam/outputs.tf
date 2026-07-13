output "ctrl_instance_profile" {
  description = "Instance profile name attached to ctrl-1."
  value       = aws_iam_instance_profile.ctrl.name
}

output "worker_instance_profile" {
  description = "Instance profile name attached to app-1, app-2, db-1, mon-1."
  value       = aws_iam_instance_profile.worker.name
}
