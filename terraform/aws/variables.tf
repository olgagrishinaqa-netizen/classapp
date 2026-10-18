variable "region" {
  type    = string
  default = "eu-north-1"
}

variable "name_prefix" {
  type    = string
  default = "classapp"
}

variable "instance_type" {
  description = "t3.small (2 ГБ) укладывается в кредиты free plan; сверьте в консоли, что тип доступен на вашем плане."
  type        = string
  default     = "t3.small"
}

variable "boot_disk_size_gb" {
  type    = number
  default = 30
}

variable "allowed_ssh_cidrs" {
  description = "Ограничьте адресом администратора/VPN. SSH с раннеров GitHub (deploy.yml) требует открытого 22."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "public_tcp_ports" {
  description = "Единая точка входа: 80/443 — nginx (приложение на /, Grafana на /grafana/). Prometheus — через SSH-туннель: ssh -L 9090:127.0.0.1:30900."
  type        = list(number)
  default     = [80, 443]
}

variable "backup_retention_days" {
  type    = number
  default = 14
}

variable "ssh_public_key" {
  description = "OpenSSH public key without the username prefix."
  type        = string
}
