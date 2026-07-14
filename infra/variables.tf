# Input variables for the main stack.

variable "admin_cidrs" {
  description = "Your public IP(s) as /32 CIDRs (list). Allowed from the internet to SSH (22), Grafana (3000), dashboard (3001), and the agent API (8080). Values live in terraform.tfvars (gitignored)."
  type        = list(string)
}

variable "alert_email" {
  description = "Email for the $100 hard-stop budget alerts."
  type        = string
  default     = "lawrence.liu10@gmail.com"
}
