data "aws_iam_policy_document" "pod_assume_role" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
    actions = [
      "sts:AssumeRole",
      "sts:TagSession",
    ]
  }
}

resource "aws_iam_role" "service" {
  for_each = local.services

  name               = "${local.name}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.pod_assume_role.json
}

data "aws_iam_policy_document" "service" {
  for_each = local.services

  statement {
    sid    = "DomainTable"
    effect = "Allow"
    actions = [
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:DeleteItem",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:UpdateItem",
    ]
    resources = [aws_dynamodb_table.domain.arn]
  }

  dynamic "statement" {
    for_each = contains(["incident-service", "work-order-service"], each.key) ? [1] : []
    content {
      sid       = "EventQueue"
      effect    = "Allow"
      actions   = ["sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ReceiveMessage", "sqs:SendMessage", "sqs:DeleteMessage"]
      resources = [aws_sqs_queue.events.arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "incident-service" ? [1] : []
    content {
      sid       = "AlertTopic"
      effect    = "Allow"
      actions   = ["sns:Publish"]
      resources = [aws_sns_topic.alerts.arn]
    }
  }

  dynamic "statement" {
    for_each = contains(["knowledge-service", "ai-analysis-service"], each.key) ? [1] : []
    content {
      sid    = "KnowledgeDocuments"
      effect = "Allow"
      actions = [
        "s3:GetObject",
        "s3:ListBucket",
      ]
      resources = [
        aws_s3_bucket.documents.arn,
        "${aws_s3_bucket.documents.arn}/*",
      ]
    }
  }

  dynamic "statement" {
    for_each = each.key == "knowledge-service" ? [1] : []
    content {
      sid       = "WriteKnowledgeDocuments"
      effect    = "Allow"
      actions   = ["s3:DeleteObject", "s3:PutObject"]
      resources = ["${aws_s3_bucket.documents.arn}/*"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "ai-analysis-service" ? [1] : []
    content {
      sid       = "InvokeFoundationModel"
      effect    = "Allow"
      actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      resources = ["arn:aws:bedrock:${var.aws_region}::foundation-model/*"]
    }
  }

  dynamic "statement" {
    for_each = contains(["knowledge-service", "ai-analysis-service"], each.key) ? [1] : []
    content {
      sid       = "RetrieveKnowledge"
      effect    = "Allow"
      actions   = ["bedrock:Retrieve"]
      resources = [aws_bedrockagent_knowledge_base.main.arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "knowledge-service" ? [1] : []
    content {
      sid       = "SynchronizeKnowledge"
      effect    = "Allow"
      actions   = ["bedrock:StartIngestionJob"]
      resources = [aws_bedrockagent_knowledge_base.main.arn]
    }
  }
}

resource "aws_iam_role_policy" "service" {
  for_each = local.services

  name   = "${local.name}-${each.key}"
  role   = aws_iam_role.service[each.key].id
  policy = data.aws_iam_policy_document.service[each.key].json
}

resource "aws_eks_pod_identity_association" "service" {
  for_each = local.services

  cluster_name    = module.eks.cluster_name
  namespace       = "ax-sentinel"
  service_account = each.key
  role_arn        = aws_iam_role.service[each.key].arn
}
