# FastAPI app (backend/) packaged by build_lambda.sh and wrapped by lambda_handler.py.

locals {
  lambda_zip = "${path.module}/build/api.zip"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/mc-ec2-api"
  retention_in_days = 0 # never expire
}

resource "aws_lambda_function" "api" {
  function_name    = "mc-ec2-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "lambda_handler.handler"
  filename         = local.lambda_zip
  source_code_hash = filebase64sha256(local.lambda_zip)
  timeout          = 15
  memory_size      = 512

  environment {
    variables = {
      MOCK_MODE            = "false"
      COGNITO_USER_POOL_ID = aws_cognito_user_pool.main.id
      COGNITO_CLIENT_ID    = aws_cognito_user_pool_client.web.id
      DB_CLUSTER_ARN       = aws_rds_cluster.db.arn
      DB_SECRET_ARN        = aws_rds_cluster.db.master_user_secret[0].secret_arn
      DB_NAME              = aws_rds_cluster.db.database_name
      LAUNCH_TEMPLATE_ID   = aws_launch_template.minecraft.id
      MAX_SERVERS_PER_USER = var.max_servers_per_user
      MAX_SERVERS_TOTAL    = var.max_servers_total
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.api.name
  }
}
