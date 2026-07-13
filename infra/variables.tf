# Input variables for the main stack.

variable "admin_cidr" {
  description = "Your single public IP as a /32 CIDR. Allowed from the internet to SSH (22), Grafana (3000), dashboard (3001), and the agent API (8080). Value lives in terraform.tfvars (gitignored)."
  type        = string
}

variable "alert_email" {
  description = "Email for the $100 hard-stop budget alerts."
  type        = string
  default     = "lawrence.liu10@gmail.com"
}
