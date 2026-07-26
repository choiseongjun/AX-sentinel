#!/bin/sh
set -eu

region="${AWS_DEFAULT_REGION:-ap-northeast-2}"
bucket="${S3_BUCKET:-axsentinel-local}"
queue="${SQS_QUEUE:-axsentinel-events}"
topic="${SNS_TOPIC:-axsentinel-alerts}"
table="${DYNAMODB_TABLE:-axsentinel-domain}"
secret="${SECRET_NAME:-axsentinel/local}"

echo "Bootstrapping AXSentinel resources in ${region}..."

if ! awslocal s3api head-bucket --bucket "${bucket}" >/dev/null 2>&1; then
  if [ "${region}" = "us-east-1" ]; then
    awslocal s3api create-bucket --bucket "${bucket}" >/dev/null
  else
    awslocal s3api create-bucket \
      --bucket "${bucket}" \
      --create-bucket-configuration "LocationConstraint=${region}" >/dev/null
  fi
fi

awslocal sqs create-queue --queue-name "${queue}" >/dev/null
awslocal sns create-topic --name "${topic}" >/dev/null

if ! awslocal dynamodb describe-table --table-name "${table}" >/dev/null 2>&1; then
  awslocal dynamodb create-table \
    --table-name "${table}" \
    --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
    --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST >/dev/null
fi

if ! awslocal secretsmanager describe-secret --secret-id "${secret}" >/dev/null 2>&1; then
  awslocal secretsmanager create-secret \
    --name "${secret}" \
    --secret-string '{"environment":"local"}' >/dev/null
fi

echo "AXSentinel LocalStack bootstrap complete."
