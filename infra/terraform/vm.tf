data "yandex_compute_image" "ubuntu" {
  family = "ubuntu-2204-lts"
}

resource "yandex_compute_instance" "vm" {
  name        = "classapp-vm"
  platform_id = "standard-v3"

  resources {
    cores  = 2
    memory = 2
  }

  boot_disk {
    initialize_params {
      image_id = data.yandex_compute_image.ubuntu.id
      size     = 20
    }
  }

  network_interface {
    subnet_id          = yandex_vpc_subnet.subnet.id
    nat                = true
    security_group_ids = [yandex_vpc_security_group.sg.id]
  }

  metadata = {
    ssh-keys = "ubuntu:${var.vm_public_ssh_key}"
    user-data = <<-CLOUD
      #cloud-config
      packages:
        - docker.io
        - docker-compose-plugin
      runcmd:
        - [ bash, -lc, "usermod -aG docker ubuntu" ]
    CLOUD
  }
}

output "vm_public_ip" {
  value = yandex_compute_instance.vm.network_interface.0.nat_ip_address
}
