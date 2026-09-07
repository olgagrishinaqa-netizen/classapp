data "yandex_compute_image" "ubuntu" {
  family = "ubuntu-2204-lts"
}

resource "yandex_compute_instance" "vm" {
  name        = "classapp-vm"
  platform_id = "standard-v3"

  scheduling_policy {
    preemptible = true
  }

  resources {
    cores         = 2
    core_fraction = 50
    memory        = 2
  }

  boot_disk {
    initialize_params {
      image_id = data.yandex_compute_image.ubuntu.id
      size     = 15
      type     = "network-hdd"
    }
  }

  network_interface {
    subnet_id          = yandex_vpc_subnet.subnet.id
    nat                = true
    nat_ip_address     = yandex_vpc_address.static_ip.external_ipv4_address[0].address # Привязка статики
    security_group_ids = [yandex_vpc_security_group.sg.id]
  }

  metadata = {
    ssh-keys = "ubuntu:${var.vm_public_ssh_key}"
    user-data = <<-CLOUD
      #cloud-config
      swap:
        filename: /swapfile
        size: 2147483648
        maxsize: 2147483648
      packages:
        - docker.io
        - docker-compose-plugin
        - python3-yaml
      runcmd:
        - [ bash, -lc, "usermod -aG docker ubuntu" ]
    CLOUD
  }
}

output "vm_public_ip" {
  value = yandex_compute_instance.vm.network_interface.0.nat_ip_address
}
