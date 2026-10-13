# Tables are created through the RDS Data API (the cluster has no direct network access).
# db/run_sql.py records applied migrations in schema_migrations, so reruns are safe.

locals {
  db_env = {
    DB_CLUSTER_ARN = aws_rds_cluster.db.arn
    DB_SECRET_ARN  = aws_rds_cluster.db.master_user_secret[0].secret_arn
    DB_NAME        = aws_rds_cluster.db.database_name
    AWS_REGION     = "us-east-1"
  }
}

resource "terraform_data" "db_migrations" {
  triggers_replace = [
    for f in sort(fileset("${path.module}/db/migrations", "*.sql")) : filesha256("${path.module}/db/migrations/${f}")
  ]

  provisioner "local-exec" {
    command     = "python3 db/run_sql.py migrate"
    working_dir = path.module
    environment = local.db_env
  }

  depends_on = [aws_rds_cluster_instance.db]
}

# Stable IDs for the seeded rows, so Terraform can output the admin's server ID.
resource "random_uuid" "admin_user" {}

resource "random_uuid" "admin_server" {}

resource "terraform_data" "db_seed_admin" {
  triggers_replace = [
    filesha256("${path.module}/db/seed_admin.sql"),
    aws_cognito_user.admin.sub,
    aws_instance.minecraft.id,
    random_uuid.admin_user.result,
    random_uuid.admin_server.result,
  ]

  provisioner "local-exec" {
    command     = "python3 db/run_sql.py apply db/seed_admin.sql"
    working_dir = path.module
    environment = merge(local.db_env, {
      SQL_PARAM_user_id       = random_uuid.admin_user.result
      SQL_PARAM_name          = var.admin_name
      SQL_PARAM_sub           = aws_cognito_user.admin.sub
      SQL_PARAM_server_id     = random_uuid.admin_server.result
      SQL_PARAM_instance_id   = aws_instance.minecraft.id
      SQL_PARAM_region        = "us-east-1"
      SQL_PARAM_version       = "LATEST" # matches VERSION in minecraft/user_data.sh
      SQL_PARAM_instance_type = aws_instance.minecraft.instance_type
    })
  }

  depends_on = [terraform_data.db_migrations]
}
