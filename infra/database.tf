# Aurora Serverless v2 (PostgreSQL) with the RDS Data API. Lambda reaches it over HTTPS,
# so the cluster uses the default VPC's subnet group and security group with no inbound access needed.

resource "aws_rds_cluster" "db" {
  cluster_identifier   = "mc-ec2"
  engine               = "aurora-postgresql"
  engine_mode          = "provisioned"
  engine_version       = "17.9"
  database_name        = "mcec2"
  master_username      = "mcadmin"
  enable_http_endpoint = true

  db_subnet_group_name   = "default"
  vpc_security_group_ids = ["sg-0ae5c67b8b3b2cb9e"] # default VPC security group

  storage_encrypted       = true
  backup_retention_period = 7
  copy_tags_to_snapshot   = true
  deletion_protection     = false
  skip_final_snapshot     = true

  performance_insights_enabled          = true
  performance_insights_retention_period = 7
  database_insights_mode                = "standard"

  serverlessv2_scaling_configuration {
    min_capacity             = 0
    max_capacity             = 2
    seconds_until_auto_pause = 300
  }

  lifecycle {
    prevent_destroy = true
    # Set by the console (password managed in Secrets Manager); not tracked on import.
    ignore_changes = [manage_master_user_password, enable_global_write_forwarding, enable_local_write_forwarding]
  }
}

resource "aws_rds_cluster_instance" "db" {
  identifier         = "mc-ec2-instance-1"
  cluster_identifier = aws_rds_cluster.db.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.db.engine
  engine_version     = aws_rds_cluster.db.engine_version

  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  lifecycle {
    prevent_destroy = true
  }
}
