# Compute module — the 5-host fleet + one SSH key pair.
#
# Key pair: Terraform generates an ED25519 key, registers the public half with
# EC2, and stores the private half both in SSM (SecureString, our KMS key) and
# in a local gitignored file so `ssh -i` works immediately. TRADEOFF: a
# Terraform-generated private key is stored in the (encrypted, S3) state; a
# hardened prod setup would generate it off-box and import only the public key.

# AMI is pinned via var.ami_id (Ubuntu 24.04 noble amd64, Canonical 099720109477).
# We deliberately avoid a most_recent data source: a newly published Canonical
# image would change the resolved id and force-replace the entire running fleet.
# var.ami_id's description documents how to refresh the pin.

resource "tls_private_key" "ssh" {
  algorithm = "ED25519"
}

resource "aws_key_pair" "sentinel" {
  key_name   = "sentinel"
  public_key = tls_private_key.ssh.public_key_openssh
}

resource "aws_ssm_parameter" "ssh_private_key" {
  name   = "/sentinel/ssh_private_key"
  type   = "SecureString"
  key_id = var.secrets_kms_key_id
  value  = tls_private_key.ssh.private_key_openssh

  tags = { Name = "sentinel-ssh_private_key" }
}

resource "local_sensitive_file" "ssh_private_key" {
  filename        = "${path.root}/.ssh/sentinel_ed25519"
  content         = tls_private_key.ssh.private_key_openssh
  file_permission = "0600"
}

# Fleet definition. Roles/sizes/ports are the contracts §1 map (ctrl-1 downsized
# to t3.micro). app/db/mon carry the worker profile; ctrl-1 carries the control
# profile (Bedrock + EC2 start/stop).
locals {
  hosts = {
    "app-1"  = { size = "t3.small", role = "app", sg = var.sg_app_id, profile = var.worker_instance_profile, disk = 8 }
    "app-2"  = { size = "t3.small", role = "app", sg = var.sg_app_id, profile = var.worker_instance_profile, disk = 8 }
    "db-1"   = { size = "t3.small", role = "db", sg = var.sg_db_id, profile = var.worker_instance_profile, disk = 15 }
    "mon-1"  = { size = "t3.medium", role = "monitoring", sg = var.sg_mon_id, profile = var.worker_instance_profile, disk = 16 }
    "ctrl-1" = { size = "t3.micro", role = "control", sg = var.sg_ctrl_id, profile = var.ctrl_instance_profile, disk = 8 }
  }
}

resource "aws_instance" "host" {
  for_each = local.hosts

  ami                    = var.ami_id
  instance_type          = each.value.size
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [each.value.sg]
  iam_instance_profile   = each.value.profile
  key_name               = aws_key_pair.sentinel.key_name

  root_block_device {
    volume_type = "gp3"
    volume_size = each.value.disk
    encrypted   = true
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 only — blocks SSRF-based credential theft
  }

  tags = {
    Name = "sentinel-${each.key}"
    Role = each.value.role
  }
}
