# Развёртывание classapp с нуля одной командой:  make up
#
#   make up        инфраструктура (Terraform) -> настройка ноды (Ansible) -> деплой приложения
#   make infra     только Terraform (состояние — в S3, создаётся автоматически)
#   make configure только Ansible (inventory + playbook)
#   make deploy    только деплой приложения (манифесты k8s, миграции, rollout)
#   make start|stop|status  вручную запустить/остановить ВМ (по умолчанию её включает и выключает расписание)
#   make github-secrets     записать в GitHub секреты SSH_HOST и SSH_KNOWN_HOSTS (нужен gh)
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
AWS_REGION  ?= eu-north-1
# make configure MONITORING=true — поставить Prometheus/Grafana (на 2 ГБ RAM не помещается)
MONITORING  ?= false
FORCE       ?= 0
SSH_OPTS    := -i $(SSH_KEY) -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20

.PHONY: up infra tf-init configure deploy destroy check preflight start stop status github-secrets

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

# Состояние Terraform — в S3 (бакет и таблицу блокировок создаёт bootstrap-state.sh,
# идемпотентно). Первый запуск сам переносит старое локальное состояние в S3.
tf-init:
	BACKEND_ARGS="$$(./terraform/bootstrap-state.sh)"; \
	terraform -chdir=$(TF_DIR) init -input=false -migrate-state -force-copy $$BACKEND_ARGS

# Применяется сохранённый план; если он удаляет/пересоздаёт ресурсы — спросит подтверждение
# (make infra FORCE=1 — без вопросов).
infra: tf-init
	TF_VAR_ssh_public_key="$$(cat $(SSH_PUBKEY))" FORCE=$(FORCE) \
	  ./terraform/safe-apply.sh $(TF_DIR)

configure:
	ANSIBLE_SSH_PRIVATE_KEY_FILE=$(SSH_KEY) ./terraform/generate_inventory.sh
	@# k3s_token создаётся один раз и переиспользуется (иначе новые ноды не присоединятся).
	@[ -f ansible/group_vars/vault.yml ] || { \
	  echo "k3s_token: \"$$(openssl rand -hex 32)\"" > ansible/group_vars/vault.yml; \
	  chmod 600 ansible/group_vars/vault.yml; }
	cd ansible && ansible-galaxy collection install -r requirements.yml
	@# Пароли bootstrap_secrets показываются только при первом прогоне — лог дописываем (tee -a),
	@# чтобы повторный прогон не стёр сохранённые пароли.
	cd ansible && ANSIBLE_HOST_KEY_CHECKING=False \
	  ansible-playbook -i inventory/hosts.ini playbook.yml -e monitoring_enabled=$(MONITORING) 2>&1 | tee -a last-run.log
	@chmod 600 ansible/last-run.log

deploy: tf-init
	@HOST="$$(terraform -chdir=$(TF_DIR) output -raw master1_static_ip)"; \
	SHA="$$(git ls-remote origin refs/heads/$(GIT_BRANCH) | cut -f1)"; \
	[ -n "$$SHA" ] || { echo "Не удалось получить коммит origin/$(GIT_BRANCH)"; exit 1; }; \
	echo "Деплой коммита $$SHA на $$HOST (образ main-$$SHA должен быть в GHCR)"; \
	tar czf - k8s scripts/pull-deploy | ssh $(SSH_OPTS) $(SSH_USER)@$$HOST \
	  'sudo mkdir -p /opt/classapp/repo && sudo chown -R $(SSH_USER): /opt/classapp && tar xzf - -C /opt/classapp/repo'; \
	ssh $(SSH_OPTS) $(SSH_USER)@$$HOST \
	  "sudo IMAGE_REPO='$$(git remote get-url origin | sed -E 's#.*github.com[:/]([^.]+)(\.git)?#\1#' | tr A-Z a-z)' \
	   SRC_DIR=/opt/classapp/repo bash /opt/classapp/repo/scripts/pull-deploy/deploy-steps.sh $$SHA"

# Прописывает в GitHub секреты деплоя: адрес ВМ и её SSH-отпечаток (защита от подмены сервера).
# Нужен gh (gh auth login). Приватный ключ SSH_KEY один раз добавьте вручную:  gh secret set SSH_KEY < ~/.ssh/id_rsa
github-secrets: tf-init
	@command -v gh >/dev/null || { echo "Нужен GitHub CLI: gh auth login"; exit 1; }
	@HOST="$$(terraform -chdir=$(TF_DIR) output -raw master1_static_ip)"; \
	gh secret set SSH_HOST --body "$$HOST"; \
	ssh-keyscan -H "$$HOST" 2>/dev/null | gh secret set SSH_KNOWN_HOSTS; \
	echo "Секреты SSH_HOST и SSH_KNOWN_HOSTS обновлены для $$HOST"

start:
	aws ec2 start-instances --region $(AWS_REGION) --instance-ids "$$(terraform -chdir=$(TF_DIR) output -json k3s_nodes | jq -r '.["master-1"].id')" --query 'StartingInstances[].CurrentState.Name' --output text

stop:
	aws ec2 stop-instances --region $(AWS_REGION) --instance-ids "$$(terraform -chdir=$(TF_DIR) output -json k3s_nodes | jq -r '.["master-1"].id')" --query 'StoppingInstances[].CurrentState.Name' --output text

status:
	aws ec2 describe-instances --region $(AWS_REGION) --instance-ids "$$(terraform -chdir=$(TF_DIR) output -json k3s_nodes | jq -r '.["master-1"].id')" --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output text

destroy: tf-init
	@read -r -p "Удалить ВСЮ инфраструктуру (ВМ, EIP, S3-бэкапы)? Введите 'yes': " a; [ "$$a" = yes ]
	TF_VAR_ssh_public_key="$$(cat $(SSH_PUBKEY))" \
	  terraform -chdir=$(TF_DIR) destroy -input=false -auto-approve

check:
	pre-commit run --all-files --hook-stage push
	pytest -q --cov=app --cov-fail-under=70
	pip-audit -r requirements.txt --progress-spinner off
	terraform fmt -check -recursive terraform
	terraform -chdir=$(TF_DIR) init -backend=false -input=false
	terraform -chdir=$(TF_DIR) validate
	cd ansible && ansible-lint playbook.yml
