# Inputs for the network module. Sensible defaults for the CIDR layout; the
# caller must supply admin_cidrs (the public IP(s) allowed to reach SSH and
# the your-eyes-only web UIs).

variable "vpc_cidr" {
  description = "CIDR block for the Sentinel VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the two public subnets (one per AZ)."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "azs" {
  description = "Availability zones for the public subnets."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "admin_cidrs" {
  description = "List of /32 CIDRs allowed from the public internet to SSH (22), Grafana (3000), the dashboard (3001), and the agent API (8080)."
  type        = list(string)
}
