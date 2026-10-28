variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  type    = string
  default = "zapagent"
}

variable "whatsapp_app_secret" {
  type      = string
  sensitive = true
}

variable "whatsapp_verify_token" {
  type      = string
  sensitive = true
}

variable "max_receive_count" {
  type    = number
  default = 3
}

variable "media_retention_days" {
  type    = number
  default = 90
}
