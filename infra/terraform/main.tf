# Hospitality Agent Cloud - Terraform AWS Infrastructure Configuration

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  default = "us-east-1"
}

variable "environment" {
  default = "production"
}

# --- VPC & NETWORKING ---
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "hospitality-agent-vpc-${var.environment}"
    Environment = var.environment
  }
}

# --- RDS POSTGRESQL WITH PGVECTOR ---
resource "aws_db_subnet_group" "db_subnets" {
  name       = "hospitality-agent-db-subnets"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "${var.aws_region}a"
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = "${var.aws_region}b"
}

resource "aws_db_instance" "postgres" {
  identifier             = "hospitality-agent-db-${var.environment}"
  allocated_storage      = 50
  max_allocated_storage  = 200
  engine                 = "postgres"
  engine_version         = "15.4"
  instance_class         = "db.r6g.xlarge"
  db_name                = "hospitality_agent_cloud"
  username               = "postgres"
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.db_subnets.name
  skip_final_snapshot    = true
  vpc_security_group_ids = [aws_security_group.db_sg.id]
}

resource "aws_security_group" "db_sg" {
  name   = "hospitality-agent-db-sg"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }
}

variable "db_password" {
  type      = string
  sensitive = true
}

# --- ELASTICACHE REDIS ---
resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "hospitality-agent-redis"
  engine               = "redis"
  node_type            = "cache.t4g.small"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
}

# --- S3 & CLOUDFRONT CDN FOR EMBEDDABLE WIDGET ---
resource "aws_s3_bucket" "widget_cdn" {
  bucket = "hospitality-agent-widget-cdn-${var.environment}"
}

resource "aws_cloudfront_distribution" "widget_distribution" {
  origin {
    domain_name = aws_s3_bucket.widget_cdn.bucket_regional_domain_name
    origin_id   = "S3-Widget-CDN"
  }

  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "widget.js"

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "S3-Widget-CDN"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 86400
    max_ttl                = 31536000
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
