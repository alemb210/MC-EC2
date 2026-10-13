# One-time imports of resources originally created in the AWS console.
# Safe to delete after the first successful apply.

# --- Database ---
import {
  to = aws_rds_cluster.db
  id = "mc-ec2"
}
import {
  to = aws_rds_cluster_instance.db
  id = "mc-ec2-instance-1"
}

# --- API: IAM ---
import {
  to = aws_iam_role.api
  id = "mc-ec2-api"
}
import {
  to = aws_iam_role_policy.api
  id = "mc-ec2-api:mc-ec2-api-access"
}
import {
  to = aws_iam_role_policy_attachment.api_logs
  id = "mc-ec2-api/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# --- API: Lambda ---
import {
  to = aws_lambda_function.api
  id = "mc-ec2-api"
}
import {
  to = aws_cloudwatch_log_group.api
  id = "/aws/lambda/mc-ec2-api"
}
import {
  to = aws_lambda_permission.apigw
  id = "mc-ec2-api/062a644b-afea-54ea-a7f5-431f54e840fc"
}

# --- API: API Gateway ---
import {
  to = aws_apigatewayv2_api.api
  id = "k19j61rb5c"
}
import {
  to = aws_apigatewayv2_integration.lambda
  id = "k19j61rb5c/f8bty13"
}
import {
  to = aws_apigatewayv2_route.default
  id = "k19j61rb5c/l9m1kj7"
}
import {
  to = aws_apigatewayv2_stage.default
  id = "k19j61rb5c/$default"
}

# --- Minecraft ---
import {
  to = aws_instance.minecraft
  id = "i-091bf005bb67f4310"
}
import {
  to = aws_launch_template.minecraft
  id = "lt-0df39f6adbd5f431e"
}
import {
  to = aws_security_group.minecraft
  id = "sg-04397b979c1c09487"
}
import {
  to = aws_iam_role.minecraft
  id = "mc-ec2"
}
import {
  to = aws_iam_instance_profile.minecraft
  id = "mc-ec2"
}
import {
  to = aws_iam_role_policy_attachment.minecraft_ssm
  id = "mc-ec2/arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
import {
  to = aws_iam_role_policy_attachment.minecraft_cloudwatch
  id = "mc-ec2/arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# --- Billing ---
import {
  to = aws_budgets_budget.monthly
  id = "506007020488:My Monthly Cost Budget"
}
