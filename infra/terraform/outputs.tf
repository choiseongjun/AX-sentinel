output "cluster_name" {
  value = module.eks.cluster_name
}

output "configure_kubectl" {
  value = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}

output "ecr_repository_urls" {
  value = { for name, repository in aws_ecr_repository.service : name => repository.repository_url }
}

output "documents_bucket" {
  value = aws_s3_bucket.documents.id
}

output "events_queue_url" {
  value = aws_sqs_queue.events.url
}

output "events_dlq_url" {
  value = aws_sqs_queue.events_dlq.url
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_web_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "cognito_issuer" {
  value = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
}

output "cognito_managed_login_domain" {
  value = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "bedrock_knowledge_base_id" {
  value = aws_bedrockagent_knowledge_base.main.id
}

output "bedrock_data_source_id" {
  value = aws_bedrockagent_data_source.documents.data_source_id
}
