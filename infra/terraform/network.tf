resource "yandex_vpc_network" "net" {
  name = "classapp-network"
}

resource "yandex_vpc_subnet" "subnet" {
  name           = "classapp-subnet"
  zone           = "ru-central1-a"
  network_id     = yandex_vpc_network.net.id
  v4_cidr_blocks = ["10.10.0.0/24"]
}

# РЕЗЕРВИРУЕМ ПОСТОЯННЫЙ (СТАТИЧЕСКИЙ) IP-АДРЕС В ОБЛАКЕ
resource "yandex_vpc_address" "static_ip" {
  name = "classapp-static-ip"
  external_ipv4_address {
    zone_id = "ru-central1-a"
  }
}

resource "yandex_vpc_security_group" "sg" {
  name       = "classapp-sg"
  network_id = yandex_vpc_network.net.id

  ingress {
    protocol       = "TCP"
    description    = "SSH"
    v4_cidr_blocks = ["0.0.0.0/0"]
    port           = 22
  }

  ingress {
    protocol       = "TCP"
    description    = "HTTP"
    v4_cidr_blocks = ["0.0.0.0/0"]
    port           = 80
  }

  egress {
    protocol       = "ANY"
    description    = "Outbound traffic"
    v4_cidr_blocks = ["0.0.0.0/0"]
    from_port      = 0
    to_port        = 65535
  }
}
