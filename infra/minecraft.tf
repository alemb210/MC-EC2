# Minecraft server: Docker (itzg/minecraft-server) on EC2, world data on the root EBS volume.
# Running/stopped state is controlled by the API, not Terraform.

resource "aws_security_group" "minecraft" {
  name        = "launch-wizard-2"
  description = "launch-wizard-2 created 2026-09-23T18:39:40.229Z"
  vpc_id      = "vpc-0afbd4c03ce12d7bf"

  ingress {
    description = ""
    from_port   = 25565
    to_port     = 25565
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = ""
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["146.95.32.113/32"]
  }

  egress {
    description = ""
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "minecraft" {
  name = "mc-ec2"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "minecraft_ssm" {
  role       = aws_iam_role.minecraft.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "minecraft_cloudwatch" {
  role       = aws_iam_role.minecraft.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_instance_profile" "minecraft" {
  name = "mc-ec2"
  role = aws_iam_role.minecraft.name
}

resource "aws_launch_template" "minecraft" {
  name                                 = "mc-ec2"
  image_id                             = "ami-0eb45f74aa8a20238"
  instance_type                        = "t4g.small"
  key_name                             = "mc-ec2"
  ebs_optimized                        = "true"
  instance_initiated_shutdown_behavior = "stop"
  user_data                            = base64encode(file("${path.module}/minecraft/user_data.sh"))

  iam_instance_profile {
    arn = aws_iam_instance_profile.minecraft.arn
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      delete_on_termination = "true"
      encrypted             = "false"
      iops                  = 3000
      snapshot_id           = "snap-0c26a50a75e8be345"
      throughput            = 125
      volume_size           = 30
      volume_type           = "gp3"
    }
  }

  network_interfaces {
    associate_public_ip_address = "true"
    delete_on_termination       = "true"
    device_index                = 0
    interface_type              = "interface"
    security_groups             = [aws_security_group.minecraft.id]
    subnet_id                   = "subnet-0f1ac5a6d310e56f4"
  }

  capacity_reservation_specification {
    capacity_reservation_preference = "open"
  }

  credit_specification {
    cpu_credits = "unlimited"
  }

  enclave_options {
    enabled = false
  }

  hibernation_options {
    configured = false
  }

  maintenance_options {
    auto_recovery = "default"
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 2
    http_tokens                 = "required"
    instance_metadata_tags      = "disabled"
  }

  network_performance_options {
    bandwidth_weighting = "default"
  }

  monitoring {
    enabled = false
  }

  placement {
    tenancy = "default"
  }

  private_dns_name_options {
    enable_resource_name_dns_a_record    = true
    enable_resource_name_dns_aaaa_record = false
    hostname_type                        = "ip-name"
  }
}

resource "aws_instance" "minecraft" {
  ami                                  = "ami-0eb45f74aa8a20238"
  instance_type                        = "t4g.small"
  key_name                             = "mc-ec2"
  subnet_id                            = "subnet-0f1ac5a6d310e56f4"
  vpc_security_group_ids               = [aws_security_group.minecraft.id]
  iam_instance_profile                 = aws_iam_instance_profile.minecraft.name
  ebs_optimized                        = true
  instance_initiated_shutdown_behavior = "stop"

  # The API's IAM policy only allows start/stop on instances with this tag.
  tags = {
    Project = "mc-ec2"
  }

  credit_specification {
    cpu_credits = "unlimited"
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 2
    http_tokens                 = "required"
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    delete_on_termination = true # world data lives here; prevent_destroy below guards it
    encrypted             = false
    iops                  = 3000
    throughput            = 125
    volume_size           = 30
    volume_type           = "gp3"
  }

  lifecycle {
    prevent_destroy = true
    # Changing any of these would replace the instance (and its world data).
    ignore_changes = [ami, user_data, user_data_base64, associate_public_ip_address]
  }
}
