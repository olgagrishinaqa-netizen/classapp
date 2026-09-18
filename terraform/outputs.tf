output "network_id" {
  value = yandex_vpc_network.classapp.id
}

output "subnet_ids" {
  value = { for name, subnet in yandex_vpc_subnet.classapp : name => subnet.id }
}

output "k3s_nodes" {
  value = {
    for name, vm in yandex_compute_instance.k3s : name => {
      id         = vm.id
      zone       = local.nodes[name].zone
      role       = local.nodes[name].role
      public_ip  = vm.network_interface[0].nat_ip_address
      private_ip = vm.network_interface[0].ip_address
    }
  }
}

output "k3s_public_ips" {
  value = {
    for name, vm in yandex_compute_instance.k3s : name => vm.network_interface[0].nat_ip_address
  }
}

output "k3s_private_ips" {
  value = {
    for name, vm in yandex_compute_instance.k3s : name => vm.network_interface[0].ip_address
  }
}
