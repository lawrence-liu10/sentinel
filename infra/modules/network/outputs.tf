# Outputs consumed by the root stack and the compute module (which places
# instances into these subnets and attaches these security groups).

output "vpc_id" {
  description = "ID of the Sentinel VPC."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "IDs of the two public subnets, in AZ order."
  value       = aws_subnet.public[*].id
}

output "sg_app_id" {
  description = "Security group for app-1/app-2."
  value       = aws_security_group.app.id
}

output "sg_db_id" {
  description = "Security group for db-1."
  value       = aws_security_group.db.id
}

output "sg_mon_id" {
  description = "Security group for mon-1."
  value       = aws_security_group.mon.id
}

output "sg_ctrl_id" {
  description = "Security group for ctrl-1."
  value       = aws_security_group.ctrl.id
}
