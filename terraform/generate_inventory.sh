#!/usr/bin/env bash
# Генерирует ansible/inventory/hosts.ini из terraform output k3s_nodes.
# Запускать из директории terraform/ после `terraform apply`.
#
# Использование:
#   cd terraform && ./generate_inventory.sh
#
# Требует: terraform, jq.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY_DIR="${SCRIPT_DIR}/../ansible/inventory"
INVENTORY_FILE="${INVENTORY_DIR}/hosts.ini"
SSH_USER="${ANSIBLE_SSH_USER:-ubuntu}"
SSH_KEY="${ANSIBLE_SSH_PRIVATE_KEY_FILE:-~/.ssh/id_ed25519}"

mkdir -p "${INVENTORY_DIR}"

nodes_json="$(terraform -chdir="${SCRIPT_DIR}" output -json k3s_nodes)"

{
    echo "# Сгенерировано автоматически: terraform/generate_inventory.sh"
    echo "# Не редактировать руками — перегенерируется при каждом terraform apply."
    echo
    echo "[k3s_master]"
    echo "${nodes_json}" | jq -r '
        to_entries[]
        | select(.value.role == "master")
        | "\(.key) ansible_host=\(.value.public_ip)"
    '
    echo
    echo "[k3s_worker]"
    echo "${nodes_json}" | jq -r '
        to_entries[]
        | select(.value.role == "worker")
        | "\(.key) ansible_host=\(.value.public_ip)"
    '
    echo
    echo "[k3s_cluster:children]"
    echo "k3s_master"
    echo "k3s_worker"
    echo
    echo "[k3s_cluster:vars]"
    echo "ansible_user=${SSH_USER}"
    echo "ansible_ssh_private_key_file=${SSH_KEY}"
} > "${INVENTORY_FILE}"

echo "Inventory записан в ${INVENTORY_FILE}"
