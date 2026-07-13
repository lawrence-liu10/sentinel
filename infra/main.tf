# Main stack — composes the per-role modules. Phase 1 order: network, ssm (owns
# the secrets KMS key), iam (grants decrypt on that key), compute (the fleet).

module "network" {
  source     = "./modules/network"
  admin_cidr = var.admin_cidr
}

module "ssm" {
  source = "./modules/ssm"
}

module "iam" {
  source              = "./modules/iam"
  secrets_kms_key_arn = module.ssm.secrets_kms_key_arn
}

module "compute" {
  source                  = "./modules/compute"
  subnet_id               = module.network.public_subnet_ids[0]
  sg_app_id               = module.network.sg_app_id
  sg_db_id                = module.network.sg_db_id
  sg_mon_id               = module.network.sg_mon_id
  sg_ctrl_id              = module.network.sg_ctrl_id
  ctrl_instance_profile   = module.iam.ctrl_instance_profile
  worker_instance_profile = module.iam.worker_instance_profile
  secrets_kms_key_id      = module.ssm.secrets_kms_key_id
}

# Lifetime $100 hard stop: emails, then auto-stops the fleet at $90 (see module).
module "budget" {
  source       = "./modules/budget"
  instance_ids = module.compute.instance_ids
  alert_email  = var.alert_email
}
