#!/usr/bin/env bash
# Создаёт (идемпотентно) хранилище состояния Terraform: S3-бакет с версионированием и
# шифрованием. Он не управляется самим Terraform (курица и яйцо) и не должен удаляться
# вместе с инфраструктурой (make destroy). Блокировки нет: оператор один, а версионирование
# позволяет откатить состояние; с Terraform >= 1.10 можно добавить use_lockfile = true.
#
# Использование: ./bootstrap-state.sh            (AWS_PROFILE / ~/.aws как обычно)
# Выводит строки backend-config для `terraform init`.
set -euo pipefail

REGION="${AWS_REGION:-eu-north-1}"
PREFIX="${STATE_PREFIX:-classapp}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${PREFIX}-tfstate-${ACCOUNT_ID}"

if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  echo "бакет состояния ${BUCKET} уже есть" >&2
else
  echo "создаю бакет состояния ${BUCKET}" >&2
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
    --create-bucket-configuration "LocationConstraint=${REGION}" >/dev/null
fi

# Применяем настройки каждый раз: это безопасно и чинит частично созданный бакет.
aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

echo "-backend-config=bucket=${BUCKET}"
echo "-backend-config=key=aws/terraform.tfstate"
echo "-backend-config=region=${REGION}"
echo "-backend-config=encrypt=true"
