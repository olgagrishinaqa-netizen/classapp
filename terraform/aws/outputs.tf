# Формат совместим с terraform/generate_inventory.sh.
output "k3s_nodes" {
  value = {
    "master-1" = {
      id         = aws_instance.k3s.id
      zone       = aws_instance.k3s.availability_zone
      role       = "master"
      public_ip  = aws_eip.master1.public_ip
      private_ip = aws_instance.k3s.private_ip
    }
  }
}

output "master1_static_ip" {
  description = "Elastic IP master-1 — значение для GitHub-секрета SSH_HOST."
  value       = aws_eip.master1.public_ip
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.bucket
}
