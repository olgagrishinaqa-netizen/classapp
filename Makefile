# Развёртывание classapp с нуля одной командой:  make up
#
#   make up        инфраструктура (Terraform) -> настройка ноды (Ansible) -> деплой приложения
#   make infra     только Terraform
#   make configure только Ansible (inventory + playbook)
#   make deploy    только деплой приложения (манифесты k8s, миграции, rollout)
#   make destroy   удалить инфраструктуру (непустой S3-бакет с бэкапами Terraform не удалит — это защита)
#   make check     проверки, как в CI (линтер, тесты, terraform validate, ansible-lint)
#
# Требуется: terraform, ansible, jq, ssh и доступ к AWS (~/.aws или AWS_* переменные).

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

TF_DIR      ?= terraform/aws
SSH_USER    ?= ubuntu
SSH_PUBKEY  ?= $(firstword $(wildcard $(HOME)/.ssh/id_ed25519.pub $(HOME)/.ssh/id_rsa.pub))
SSH_KEY     ?= $(patsubst %.pub,%,$(SSH_PUBKEY))
GIT_BRANCH  ?= main
# make configure MONITORING=true — поставить Prometheus/Grafana (на 2 ГБ RAM не помещается)
MONITORING  ?= false
SSH_OPTS    := -i $(SSH_KEY) -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20

.PHONY: up infra configure deploy destroy check preflight

up: preflight infra configure deploy
	@echo
	@echo "Готово: http://$$(terraform -chdir=$(TF_DIR) output -raw master1_static_ip)/"
	@echo "Креды администратора и Grafana выведены ролью bootstrap_secrets в ansible/last-run.log"

preflight:
	@for tool in terraform ansible-playbook ansible-galaxy jq ssh git; do \
	  command -v $$tool >/dev/null || { echo "Не найден: $$tool"; exit 1; }; \
	done
	@[ -n "$(SSH_PUBKEY)" ] && [ -f "$(SSH_KEY)" ] || { \
	  echo "Нужен SSH-ключ: ~/.ssh/id_ed25519 (или id_rsa) и .pub к нему (ssh-keygen -t ed25519)"; exit 1; }

infra:
	terraform -chdir=$(TF_DIR) init -input=false
	TF_VAR_ssh_public_key="$$(cat $(SSH_PUBKEY))" \
	  terraform -chdir=$(TF_DIR) apply -input=false -auto-approve

configure:
	ANSIBLE_SSH_PRIVATE_KEY_FILE=$(SSH_KEY) ./terraform/generate_inventory.sh
	@# k3s_token создаётся один раз и переиспользуется (иначе новые ноды не присоединятся).
	@[ -f ansible/group_vars/vault.yml ] || { \
	  echo "k3s_token: \"$$(openssl rand -hex 32)\"" > ansible/group_vars/vault.yml; \
	  chmod 600 ansible/group_vars/vault.yml; }
	cd ansible && ansible-galaxy collection install -r requirements.yml
	@# Пароли bootstrap_secrets показываются только при первом прогоне — сохраняем лог.
	cd ansible && ANSIBLE_HOST_KEY_CHECKING=False \
	  ansible-playbook -i inventory/hosts.ini playbook.yml -e monitoring_enabled=$(MONITORING) 2>&1 | tee last-run.log
	@chmod 600 ansible/last-run.log

deploy:
	@HOST="$$(terraform -chdir=$(TF_DIR) output -raw master1_static_ip)"; \
	SHA="$$(git ls-remote origin refs/heads/$(GIT_BRANCH) | cut -f1)"; \
	[ -n "$$SHA" ] || { echo "Не удалось получить коммит origin/$(GIT_BRANCH)"; exit 1; }; \
	echo "Деплой коммита $$SHA на $$HOST (образ main-$$SHA должен быть в GHCR)"; \
	tar czf - k8s scripts/pull-deploy | ssh $(SSH_OPTS) $(SSH_USER)@$$HOST \
	  'sudo mkdir -p /opt/classapp/repo && sudo chown -R $(SSH_USER): /opt/classapp && tar xzf - -C /opt/classapp/repo'; \
	ssh $(SSH_OPTS) $(SSH_USER)@$$HOST \
	  "sudo IMAGE_REPO='$$(git remote get-url origin | sed -E 's#.*github.com[:/]([^.]+)(\.git)?#\1#' | tr A-Z a-z)' \
	   SRC_DIR=/opt/classapp/repo bash /opt/classapp/repo/scripts/pull-deploy/deploy-steps.sh $$SHA"

destroy:
	@read -r -p "Удалить ВСЮ инфраструктуру (ВМ, EIP, S3-бэкапы)? Введите 'yes': " a; [ "$$a" = yes ]
	TF_VAR_ssh_public_key="$$(cat $(SSH_PUBKEY))" \
	  terraform -chdir=$(TF_DIR) destroy -input=false -auto-approve

check:
	pre-commit run --all-files --hook-stage push
	pytest -q
	terraform -chdir=$(TF_DIR) init -backend=false -input=false
	terraform -chdir=$(TF_DIR) validate
	terraform fmt -check -recursive terraform
	cd ansible && ansible-lint playbook.yml
