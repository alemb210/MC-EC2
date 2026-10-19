# Values kept out of the public repo. Set them in terraform.tfvars (gitignored).

variable "budget_alert_emails" {
  description = "Email addresses that receive AWS budget alerts"
  type        = list(string)
}

variable "admin_email" {
  description = "Email (and Cognito username) of the single admin account"
  type        = string
}

variable "admin_name" {
  description = "Display name stored in users.name for the admin"
  type        = string
  default     = "Admin"
}

variable "max_servers_per_user" {
  description = "Servers each user can create through POST /servers"
  type        = number
  default     = 1
}

variable "max_servers_total" {
  description = "Servers that can exist in total (including the admin's); bounds cost with open signup"
  type        = number
  default     = 3
}
