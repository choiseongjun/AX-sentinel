resource "aws_s3vectors_vector_bucket" "knowledge" {
  vector_bucket_name = "${local.name}-vectors"
}

resource "aws_s3vectors_index" "knowledge" {
  index_name         = "documents"
  vector_bucket_name = aws_s3vectors_vector_bucket.knowledge.vector_bucket_name

  data_type       = "float32"
  dimension       = 1024
  distance_metric = "cosine"
}

data "aws_iam_policy_document" "knowledge_base_assume_role" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:knowledge-base/*"]
    }
  }
}

resource "aws_iam_role" "knowledge_base" {
  name               = "${local.name}-knowledge-base"
  assume_role_policy = data.aws_iam_policy_document.knowledge_base_assume_role.json
}

data "aws_iam_policy_document" "knowledge_base" {
  statement {
    sid       = "EmbeddingModel"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = ["arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"]
  }

  statement {
    sid    = "SourceDocuments"
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

  statement {
    sid     = "VectorStore"
    effect  = "Allow"
    actions = ["s3vectors:*"]
    resources = [
      aws_s3vectors_vector_bucket.knowledge.vector_bucket_arn,
      aws_s3vectors_index.knowledge.index_arn,
    ]
  }
}

resource "aws_iam_role_policy" "knowledge_base" {
  name   = "${local.name}-knowledge-base"
  role   = aws_iam_role.knowledge_base.id
  policy = data.aws_iam_policy_document.knowledge_base.json
}

resource "aws_bedrockagent_knowledge_base" "main" {
  name     = local.name
  role_arn = aws_iam_role.knowledge_base.arn

  knowledge_base_configuration {
    type = "VECTOR"

    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"

      embedding_model_configuration {
        bedrock_embedding_model_configuration {
          dimensions          = 1024
          embedding_data_type = "FLOAT32"
        }
      }
    }
  }

  storage_configuration {
    type = "S3_VECTORS"

    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.knowledge.index_arn
    }
  }

  depends_on = [aws_iam_role_policy.knowledge_base]
}

resource "aws_bedrockagent_data_source" "documents" {
  knowledge_base_id    = aws_bedrockagent_knowledge_base.main.id
  name                 = "${local.name}-documents"
  data_deletion_policy = "DELETE"

  data_source_configuration {
    type = "S3"

    s3_configuration {
      bucket_arn         = aws_s3_bucket.documents.arn
      inclusion_prefixes = ["documents/"]
    }
  }

  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = "FIXED_SIZE"

      fixed_size_chunking_configuration {
        max_tokens         = 512
        overlap_percentage = 20
      }
    }
  }
}
