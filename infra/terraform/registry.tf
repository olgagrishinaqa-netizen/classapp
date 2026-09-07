resource "yandex_container_registry" "reg" {
  name = "classapp-registry"
}

output "registry_id" {
  value = yandex_container_registry.reg.id
}
