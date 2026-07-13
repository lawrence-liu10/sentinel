# Inputs for the budget hard-stop module.

variable "instance_ids" {
  description = "Fleet instance ids the auto-stop action stops when the cap is hit."
  type        = list(string)
}

variable "alert_email" {
  description = "Where budget alert emails are sent."
  type        = string
}

variable "hard_stop_limit" {
  description = "Lifetime USD cap (gross usage = credits burned) before compute auto-stops."
  type        = string
  default     = "100"
}

variable "action_threshold_percent" {
  description = "Percent of the cap at which the auto-stop fires. Below 100 on purpose: AWS billing lags, so we stop before the true $100 ceiling."
  type        = number
  default     = 90
}
