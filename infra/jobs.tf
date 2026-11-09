# Scheduled auto-stop. Same zip as the API, its own role with no database access: a query every
# 5 minutes would keep Aurora from auto-pausing, so idle time is kept in an EC2 tag.

resource "aws_cloudwatch_log_group" "jobs" {
  name              = "/aws/lambda/mc-ec2-jobs"
  retention_in_days = 30
}

resource "aws_iam_role" "jobs" {
  name        = "mc-ec2-jobs"
  description = "Scheduled jobs Lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "jobs_logs" {
  role       = aws_iam_role.jobs.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "jobs" {
  name = "mc-ec2-jobs-access"
  role = aws_iam_role.jobs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadInstanceState"
        Effect   = "Allow"
        Action   = "ec2:DescribeInstances"
        Resource = "*"
      },
      {
        Sid       = "StopTaggedInstances"
        Effect    = "Allow"
        Action    = "ec2:StopInstances"
        Resource  = "${local.ec2_arn}:instance/*"
        Condition = { StringEquals = { "aws:ResourceTag/Project" = "mc-ec2" } }
      },
      {
        Sid      = "TrackIdleTime"
        Effect   = "Allow"
        Action   = ["ec2:CreateTags", "ec2:DeleteTags"]
        Resource = "${local.ec2_arn}:instance/*"
        Condition = {
          StringEquals                = { "aws:ResourceTag/Project" = "mc-ec2" }
          "ForAllValues:StringEquals" = { "aws:TagKeys" = ["IdleSince", "NeedsBackup", "RestoreTo", "RestoreSafety", "RestoreTask", "RestoreFailed"] }
        }
      },
      {
        Sid      = "ReadBackups"
        Effect   = "Allow"
        Action   = "ec2:DescribeSnapshots"
        Resource = "*"
      },
      local.snapshot_volumes_statement,
      local.create_backups_statement,
      local.tag_backups_statement,
      local.delete_backups_statement,
      {
        Sid       = "StartRestoringInstances"
        Effect    = "Allow"
        Action    = "ec2:StartInstances"
        Resource  = "${local.ec2_arn}:instance/*"
        Condition = { StringEquals = { "aws:ResourceTag/Project" = "mc-ec2" } }
      },
      {
        Sid      = "ReadRestoreTasks"
        Effect   = "Allow"
        Action   = "ec2:DescribeReplaceRootVolumeTasks"
        Resource = "*"
      },
      {
        Sid       = "ReplaceRootOfTaggedInstances"
        Effect    = "Allow"
        Action    = "ec2:CreateReplaceRootVolumeTask"
        Resource  = "${local.ec2_arn}:instance/*"
        Condition = { StringEquals = { "aws:ResourceTag/Project" = "mc-ec2" } }
      },
      {
        Sid    = "ReplaceRootResources"
        Effect = "Allow"
        Action = "ec2:CreateReplaceRootVolumeTask"
        Resource = [
          local.snapshots_arn,
          "${local.ec2_arn}:volume/*",
          "${local.ec2_arn}:replace-root-volume-task/*",
        ]
      },
    ]
  })
}

resource "aws_lambda_function" "jobs" {
  function_name    = "mc-ec2-jobs"
  role             = aws_iam_role.jobs.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "jobs_handler.handler"
  filename         = local.lambda_zip
  source_code_hash = filebase64sha256(local.lambda_zip)
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      AUTO_STOP_IDLE_MINUTES = var.auto_stop_idle_minutes
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.jobs.name
  }
}

resource "aws_cloudwatch_event_rule" "auto_stop" {
  name                = "mc-ec2-auto-stop"
  description         = "Stops Minecraft servers that have been idle"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "auto_stop" {
  rule = aws_cloudwatch_event_rule.auto_stop.name
  arn  = aws_lambda_function.jobs.arn
}

resource "aws_lambda_permission" "auto_stop" {
  statement_id  = "AllowAutoStopSchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.jobs.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.auto_stop.arn
}
