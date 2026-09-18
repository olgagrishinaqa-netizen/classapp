variable "yc_token" {
  description = "Yandex Cloud OAuth/IAM token. Prefer TF_VAR_yc_token or a secrets manager."
  type        = string
  sensitive   = true
}

variable "cloud_id" {
  type = string
}

variable "folder_id" {
  type = string
}

variable "name_prefix" {
  type    = string
  default = "classapp"
}

variable "zones" {
  description = "Zones used for K3s control-plane nodes."
  type        = list(string)
  default     = ["ru-central1-a", "ru-central1-b"]
}

variable "worker_zones" {
  description = "Zones used for K3s worker nodes."
  type        = list(string)
  default     = ["ru-central1-c"]
}

variable "subnets" {
  type = map(object({
    zone = string
    cidr = string
  }))
  default = {
    a = { zone = "ru-central1-a", cidr = "10.20.1.0/24" }
    b = { zone = "ru-central1-b", cidr = "10.20.2.0/24" }
    c = { zone = "ru-central1-c", cidr = "10.20.3.0/24" }
  }
}

variable "allowed_ssh_cidrs" {
  description = "Restrict this to the administrator/VPN CIDR in production."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "public_tcp_ports" {
  type    = list(number)
  default = [80, 443, 3000, 30080, 30900]
}

variable "image_family" {
  type    = string
  default = "ubuntu-2204-lts"
}

variable "platform_id" {
  type    = string
  default = "standard-v3"
}

variable "vm_cores" {
  type    = number
  default = 2
}

variable "vm_memory_gb" {
  type    = number
  default = 4
}

variable "vm_core_fraction" {
  type    = number
  default = 50
}

variable "boot_disk_size_gb" {
  type    = number
  default = 30
}

variable "ssh_public_key" {
  description = "OpenSSH public key without the username prefix."
  type        = string
}
