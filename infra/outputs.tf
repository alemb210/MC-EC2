output "api_url" {
  value = aws_apigatewayv2_api.api.api_endpoint
}

output "db_cluster_arn" {
  value = aws_rds_cluster.db.arn
}

output "db_secret_arn" {
  value = aws_rds_cluster.db.master_user_secret[0].secret_arn
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "cognito_issuer" {
  value = "https://${aws_cognito_user_pool.main.endpoint}"
}

output "cognito_login_url" {
  value = "https://${aws_cognito_user_pool_domain.main.domain}.auth.us-east-1.amazoncognito.com"
}

output "admin_server_id" {
  description = "Server ID to use in /servers/{server_id}/... for the admin's Minecraft server"
  value       = random_uuid.admin_server.result
}
