terraform {
  required_version = ">= 1.6.0"

  required_providers {
    yandex = {
      source  = "yandex-cloud/yandex"
      version = "~> 0.130"
    }
  }
}

provider "yandex" {
  token     = var.yc_token
  cloud_id  = var.cloud_id
  folder_id = var.folder_id
  zone      = var.zones[0]
}

resource "yandex_vpc_network" "classapp" {
  name = "${var.name_prefix}-network"
}

resource "yandex_vpc_subnet" "classapp" {
  for_each = var.subnets

  name           = "${var.name_prefix}-${each.key}"
  zone           = each.value.zone
  network_id     = yandex_vpc_network.classapp.id
  v4_cidr_blocks = [each.value.cidr]
}

resource "yandex_vpc_security_group" "k3s" {
  name       = "${var.name_prefix}-k3s"
  network_id = yandex_vpc_network.classapp.id

  dynamic "ingress" {
    for_each = var.allowed_ssh_cidrs
    content {
      protocol       = "TCP"
      description    = "SSH"
      v4_cidr_blocks = [ingress.value]
      port           = 22
    }
  }

  dynamic "ingress" {
    for_each = var.public_tcp_ports
    content {
      protocol       = "TCP"
      description    = "Public application and observability port"
      v4_cidr_blocks = ["0.0.0.0/0"]
      port           = ingress.value
    }
  }

  dynamic "ingress" {
    for_each = var.subnets
    content {
      protocol       = "ANY"
      description    = "K3s node-to-node traffic"
      v4_cidr_blocks = [ingress.value.cidr]
    }
  }

  egress {
    protocol       = "ANY"
    description    = "Outbound traffic"
    v4_cidr_blocks = ["0.0.0.0/0"]
    from_port      = 0
    to_port        = 65535
  }
}

data "yandex_compute_image" "ubuntu" {
  family = var.image_family
}

locals {
  nodes = merge(
    {
      for index, zone in var.zones :
      "master-${index + 1}" => {
        role = "master"
        zone = zone
      }
    },
    {
      for index, zone in var.worker_zones :
      "worker-${index + 1}" => {
        role = "worker"
        zone = zone
      }
    }
  )
}

resource "yandex_compute_instance" "k3s" {
  for_each = local.nodes

  name        = "${var.name_prefix}-${each.key}"
  platform_id = var.platform_id

  resources {
    cores         = var.vm_cores
    memory        = var.vm_memory_gb
    core_fraction = var.vm_core_fraction
  }

  scheduling_policy {
    preemptible = var.preemptible
  }

  boot_disk {
    initialize_params {
      image_id = data.yandex_compute_image.ubuntu.id
      size     = var.boot_disk_size_gb
      type     = var.boot_disk_type
    }
  }

  network_interface {
    subnet_id          = yandex_vpc_subnet.classapp[each.value.zone].id
    nat                = true
    security_group_ids = [yandex_vpc_security_group.k3s.id]
  }

  metadata = {
    ssh-keys = "ubuntu:${var.ssh_public_key}"
  }
}
