# Network module — VPC, two public subnets, an internet gateway, and one public
# route table. No NAT gateway (locked cost decision, saves ~$32/mo): instances
# live in public subnets behind tight security groups (security_groups.tf) and
# reach the internet directly through the IGW for GHCR pulls, Bedrock, and apt.

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # instances get resolvable public DNS names

  tags = { Name = "sentinel-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "sentinel-igw" }
}

# Public subnets, one per AZ. map_public_ip_on_launch = true because there is no
# NAT: every instance needs its own public IP to reach the internet. Those IPs
# rotate on stop/start, which is why the Ansible inventory is regenerated from
# Terraform output on every `make up` rather than hardcoded.
resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.azs[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "sentinel-public-${var.azs[count.index]}" }
}

# Single public route table: everything not local goes out the IGW.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "sentinel-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
