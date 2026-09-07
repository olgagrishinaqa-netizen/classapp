data "yandex_compute_image" "ubuntu" {
  family = "ubuntu-2204-lts"
}

resource "yandex_compute_instance" "vm" {
  name        = "classapp-vm"
  platform_id = "standard-v3"

  # Экономия 70%: ВМ может быть прервана облаком
  scheduling_policy {
    preemptible = true
  }

  resources {
    cores         = 2 # Минимально для v3 платформы, но мы экономим за счет прерываемости
    core_fraction = 50 # Загрузка ядра наполовину срезает базовую стоимость CPU
    memory        = 2 # 2 ГБ RAM хватит для Flask + Postgres со свопом
  }

  boot_disk {
    initialize_params {
      image_id = data.yandex_compute_image.ubuntu.id
      size     = 15  # Сжали диск до 15 ГБ HDD
      type     = "network-hdd" # Самый дешевый тип диска
    }
  }

  network_interface {
    subnet_id          = yandex_vpc_subnet.subnet.id
    nat                = true
    security_group_ids = [yandex_vpc_security_group.sg.id]
  }

  metadata = {
    ssh-keys = "ubuntu:${var.vm_public_ssh_key}"
    # Включаем автоматическое создание SWAP-файла на 2 ГБ для стабильности Postgres
    user-data = <<-CLOUD
      #cloud-config
      swap:
        filename: /swapfile
        size: 2147483648 # 2 GB SWAP
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
