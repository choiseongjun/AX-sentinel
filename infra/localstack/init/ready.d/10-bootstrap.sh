#!/bin/sh
set -eu

region="${AWS_DEFAULT_REGION:-ap-northeast-2}"
bucket="${S3_BUCKET:-axsentinel-local}"
queue="${SQS_QUEUE:-axsentinel-events}"
dlq="${SQS_DLQ:-axsentinel-events-dlq}"
topic="${SNS_TOPIC:-axsentinel-alerts}"
tables="${DYNAMODB_TABLES:-axsentinel-asset axsentinel-incident axsentinel-analysis axsentinel-knowledge axsentinel-work-order axsentinel-metrics axsentinel-events}"
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

awslocal sqs create-queue --queue-name "${dlq}" >/dev/null
dlq_arn="$(
  awslocal sqs get-queue-attributes \
    --queue-url "$(awslocal sqs get-queue-url --queue-name "${dlq}" --query QueueUrl --output text)" \
    --attribute-names QueueArn \
    --query 'Attributes.QueueArn' \
    --output text
)"
queue_url="$(
  awslocal sqs create-queue \
    --queue-name "${queue}" \
    --query QueueUrl \
    --output text
)"
queue_attributes="$(
  printf \
    '{"VisibilityTimeout":"60","RedrivePolicy":"{\\"deadLetterTargetArn\\":\\"%s\\",\\"maxReceiveCount\\":\\"3\\"}"}' \
    "${dlq_arn}"
)"
awslocal sqs set-queue-attributes \
  --queue-url "${queue_url}" \
  --attributes "${queue_attributes}" >/dev/null
awslocal sns create-topic --name "${topic}" >/dev/null

for table in ${tables}; do
  if ! awslocal dynamodb describe-table --table-name "${table}" >/dev/null 2>&1; then
    awslocal dynamodb create-table \
      --table-name "${table}" \
      --attribute-definitions \
        AttributeName=pk,AttributeType=S \
        AttributeName=sk,AttributeType=S \
        AttributeName=entity_type,AttributeType=S \
        AttributeName=updated_at,AttributeType=S \
      --key-schema \
        AttributeName=pk,KeyType=HASH \
        AttributeName=sk,KeyType=RANGE \
      --global-secondary-indexes \
        'IndexName=entity_type-updated_at-index,KeySchema=[{AttributeName=entity_type,KeyType=HASH},{AttributeName=updated_at,KeyType=RANGE}],Projection={ProjectionType=ALL}' \
      --billing-mode PAY_PER_REQUEST >/dev/null
  fi
done

if ! awslocal secretsmanager describe-secret --secret-id "${secret}" >/dev/null 2>&1; then
  awslocal secretsmanager create-secret \
    --name "${secret}" \
    --secret-string '{"environment":"local"}' >/dev/null
fi

echo "AXSentinel LocalStack bootstrap complete."
