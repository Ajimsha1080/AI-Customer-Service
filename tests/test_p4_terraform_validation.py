import pytest
import re
from pathlib import Path

TF_FILE = Path(__file__).parent.parent / "infra" / "terraform" / "main.tf"

def test_p4_terraform_file_exists():
    assert TF_FILE.exists(), "infra/terraform/main.tf must exist"

def test_p4_multi_az_vpc_and_subnets():
    with open(TF_FILE, "r", encoding="utf-8") as f:
        tf_content = f.read()

    # 3 AZ subnets
    assert 'resource "aws_subnet" "public_a"' in tf_content
    assert 'resource "aws_subnet" "public_b"' in tf_content
    assert 'resource "aws_subnet" "public_c"' in tf_content
    assert 'resource "aws_subnet" "private_a"' in tf_content
    assert 'resource "aws_subnet" "private_b"' in tf_content
    assert 'resource "aws_subnet" "private_c"' in tf_content

    # DB & Redis subnets span 3 AZs
    assert "subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id, aws_subnet.private_c.id]" in tf_content
    assert "subnets            = [aws_subnet.public_a.id, aws_subnet.public_b.id, aws_subnet.public_c.id]" in tf_content

def test_p4_kms_customer_managed_key():
    with open(TF_FILE, "r", encoding="utf-8") as f:
        tf_content = f.read()

    assert 'resource "aws_kms_key" "app_kms"' in tf_content
    assert "enable_key_rotation     = true" in tf_content

def test_p4_rds_postgres_16_hardening():
    with open(TF_FILE, "r", encoding="utf-8") as f:
        tf_content = f.read()

    assert 'resource "aws_db_instance" "postgres"' in tf_content
    assert 'engine_version              = "16.1"' in tf_content
    assert "multi_az                    = true" in tf_content
    assert "storage_encrypted           = true" in tf_content
    assert "kms_key_id                  = aws_kms_key.app_kms.arn" in tf_content
    assert "backup_retention_period     = 30" in tf_content
    assert "deletion_protection         = true" in tf_content

def test_p4_elasticache_redis_encryption():
    with open(TF_FILE, "r", encoding="utf-8") as f:
        tf_content = f.read()

    assert 'resource "aws_elasticache_replication_group" "redis"' in tf_content
    assert "at_rest_encryption_enabled = true" in tf_content
    assert "transit_encryption_enabled = true" in tf_content
    assert "multi_az_enabled           = true" in tf_content
    assert "kms_key_id                  = aws_kms_key.app_kms.arn" in tf_content

def test_p4_least_privilege_worker_iam():
    with open(TF_FILE, "r", encoding="utf-8") as f:
        tf_content = f.read()

    assert 'resource "aws_iam_role" "worker_node_role"' in tf_content
    assert "AmazonEKSWorkerNodePolicy" in tf_content
    assert "AmazonEKS_CNI_Policy" in tf_content
    assert "AmazonEC2ContainerRegistryReadOnly" in tf_content

def test_p4_s3_kms_versioning_and_public_block():
    with open(TF_FILE, "r", encoding="utf-8") as f:
        tf_content = f.read()

    assert 'resource "aws_s3_bucket" "rag_documents"' in tf_content
    assert 'status = "Enabled"' in tf_content
    assert 'sse_algorithm     = "aws:kms"' in tf_content
    assert 'kms_master_key_id = aws_kms_key.app_kms.arn' in tf_content
    assert "block_public_acls       = true" in tf_content
    assert "block_public_policy     = true" in tf_content

def test_p4_cloudwatch_alarms():
    with open(TF_FILE, "r", encoding="utf-8") as f:
        tf_content = f.read()

    assert 'resource "aws_cloudwatch_metric_alarm" "alb_5xx"' in tf_content
    assert 'metric_name         = "HTTPCode_Target_5XX_Count"' in tf_content

    assert 'resource "aws_cloudwatch_metric_alarm" "alb_latency"' in tf_content
    assert 'metric_name         = "TargetResponseTime"' in tf_content

    assert 'resource "aws_cloudwatch_metric_alarm" "ecs_high_cpu"' in tf_content
    assert 'metric_name         = "CPUUtilization"' in tf_content

    assert 'resource "aws_cloudwatch_metric_alarm" "ecs_high_memory"' in tf_content
    assert 'metric_name         = "MemoryUtilization"' in tf_content
