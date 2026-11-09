# Execution role for the FastAPI Lambda: logs, EC2 start/stop/terminate limited by tag, launching from
# the Minecraft launch template, Data API access, access settings, and looking up users by email.

data "aws_caller_identity" "current" {}

locals {
  ec2_arn = "arn:aws:ec2:us-east-1:${data.aws_caller_identity.current.account_id}"
  # One parameter per server, created and deleted by the API (backend/player_access.py).
  access_parameters_arn = "arn:aws:ssm:us-east-1:${data.aws_caller_identity.current.account_id}:parameter/mc-ec2/servers/*"
  snapshots_arn         = "arn:aws:ec2:us-east-1::snapshot/*"
  # Not limited by volume tag: older and replaced root volumes don't have one.
  snapshot_volumes_statement = {
    Sid      = "SnapshotVolumes"
    Effect   = "Allow"
    Action   = "ec2:CreateSnapshot"
    Resource = "${local.ec2_arn}:volume/*"
  }
  create_backups_statement = {
    Sid       = "CreateTaggedBackups"
    Effect    = "Allow"
    Action    = "ec2:CreateSnapshot"
    Resource  = local.snapshots_arn
    Condition = { StringEquals = { "aws:RequestTag/Project" = "mc-ec2" } }
  }
  tag_backups_statement = {
    Sid       = "TagBackupsAtCreation"
    Effect    = "Allow"
    Action    = "ec2:CreateTags"
    Resource  = local.snapshots_arn
    Condition = { StringEquals = { "ec2:CreateAction" = "CreateSnapshot" } }
  }
  # Requiring Kind keeps manual snapshots, which only have Project, out of reach.
  delete_backups_statement = {
    Sid      = "DeleteWorldBackups"
    Effect   = "Allow"
    Action   = "ec2:DeleteSnapshot"
    Resource = local.snapshots_arn
    Condition = {
      StringEquals = { "aws:ResourceTag/Project" = "mc-ec2" }
      StringLike   = { "aws:ResourceTag/Kind" = "*" }
    }
  }
}

resource "aws_iam_role" "api" {
  name        = "mc-ec2-api"
  description = "Backend FastAPI Lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "api_logs" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "api" {
  name = "mc-ec2-api-access"
  role = aws_iam_role.api.id
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
        Sid       = "ControlTaggedInstances"
        Effect    = "Allow"
        Action    = ["ec2:StartInstances", "ec2:StopInstances", "ec2:TerminateInstances"]
        Resource  = "arn:aws:ec2:us-east-1:${data.aws_caller_identity.current.account_id}:instance/*"
        Condition = { StringEquals = { "aws:ResourceTag/Project" = "mc-ec2" } }
      },
      # POST /servers: RunInstances only from the mc-ec2 launch template, and only with Project=mc-ec2,
      # so launched instances are exactly the ones ControlTaggedInstances covers.
      {
        Sid      = "LaunchTaggedInstanceFromTemplate"
        Effect   = "Allow"
        Action   = "ec2:RunInstances"
        Resource = "${local.ec2_arn}:instance/*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/Project" = "mc-ec2"
            "ec2:LaunchTemplate"     = aws_launch_template.minecraft.arn
          }
        }
      },
      {
        Sid       = "LaunchTaggedVolume"
        Effect    = "Allow"
        Action    = "ec2:RunInstances"
        Resource  = "${local.ec2_arn}:volume/*"
        Condition = { StringEquals = { "aws:RequestTag/Project" = "mc-ec2" } }
      },
      {
        Sid    = "LaunchTemplateResources"
        Effect = "Allow"
        Action = "ec2:RunInstances"
        Resource = [
          aws_launch_template.minecraft.arn,
          "${local.ec2_arn}:subnet/${aws_launch_template.minecraft.network_interfaces[0].subnet_id}",
          aws_security_group.minecraft.arn,
          "${local.ec2_arn}:network-interface/*",
          "${local.ec2_arn}:key-pair/${aws_launch_template.minecraft.key_name}",
          "arn:aws:ec2:us-east-1::image/${aws_launch_template.minecraft.image_id}",
          "arn:aws:ec2:us-east-1::snapshot/*",
        ]
      },
      {
        Sid       = "TagAtLaunch"
        Effect    = "Allow"
        Action    = "ec2:CreateTags"
        Resource  = ["${local.ec2_arn}:instance/*", "${local.ec2_arn}:volume/*"]
        Condition = { StringEquals = { "ec2:CreateAction" = "RunInstances" } }
      },
      {
        Sid       = "PassMinecraftRole"
        Effect    = "Allow"
        Action    = "iam:PassRole"
        Resource  = aws_iam_role.minecraft.arn
        Condition = { StringEquals = { "iam:PassedToService" = "ec2.amazonaws.com" } }
      },
      {
        Sid      = "ManageAccessSettings"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter"]
        Resource = local.access_parameters_arn
      },
      {
        Sid      = "SendSyncDocument"
        Effect   = "Allow"
        Action   = "ssm:SendCommand"
        Resource = aws_ssm_document.sync_access.arn
      },
      {
        Sid       = "SendSyncToTaggedInstances"
        Effect    = "Allow"
        Action    = "ssm:SendCommand"
        Resource  = "${local.ec2_arn}:instance/*"
        Condition = { StringEquals = { "ssm:resourceTag/Project" = "mc-ec2" } }
      },
      {
        Sid      = "FindUsersByEmail"
        Effect   = "Allow"
        Action   = "cognito-idp:ListUsers"
        Resource = aws_cognito_user_pool.main.arn
      },
      {
        Sid      = "ReadBackups"
        Effect   = "Allow"
        Action   = "ec2:DescribeSnapshots"
        Resource = "*"
      },
      local.delete_backups_statement,
      local.snapshot_volumes_statement,
      local.create_backups_statement,
      local.tag_backups_statement,
      {
        Sid      = "RequestRestores"
        Effect   = "Allow"
        Action   = ["ec2:CreateTags", "ec2:DeleteTags"]
        Resource = "${local.ec2_arn}:instance/*"
        Condition = {
          StringEquals                = { "aws:ResourceTag/Project" = "mc-ec2" }
          "ForAllValues:StringEquals" = { "aws:TagKeys" = ["RestoreTo", "RestoreSafety", "RestoreTask", "RestoreFailed", "NeedsBackup"] }
        }
      },
      {
        Sid    = "DataApi"
        Effect = "Allow"
        Action = [
          "rds-data:ExecuteStatement",
          "rds-data:BatchExecuteStatement",
          "rds-data:BeginTransaction",
          "rds-data:CommitTransaction",
          "rds-data:RollbackTransaction",
        ]
        Resource = aws_rds_cluster.db.arn
      },
      {
        Sid      = "ReadDbSecret"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_rds_cluster.db.master_user_secret[0].secret_arn
      },
    ]
  })
}
