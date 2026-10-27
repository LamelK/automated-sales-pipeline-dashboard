### ✅ variables.tf

variable "aws_region" {
  description = "The AWS region to deploy into"
  type        = string
  default     = "eu-north-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC. The subnets are carved out of it with cidrsubnet()"
  type        = string
  default     = "10.0.0.0/16"
}

variable "db_instance_type" {
  description = "Instance type for RDS"
  type        = string
  default     = "db.t3.micro"
}

variable "ec2_instance_type" {
  description = "Instance type for Metabase EC2"
  type        = string
  default     = "t3.small"
}

variable "ec2_key_name" {
  description = "Name of the SSH key pair for EC2"
  type        = string
  default     = "sales-pipeline-metabase-key"
}

variable "ssh_public_key_path" {
  description = "Path to your SSH public key (~ and absolute paths are expanded)"
  type        = string
  default     = "metabase.pub"
}

variable "db_name" {
  description = "Name of the database"
  type        = string
  default     = "electronics_shop"
}

variable "db_username" {
  description = "Username for the RDS database"
  type        = string
  default     = "admin"
}

variable "bucket_prefix" {
  description = "Name of the S3 bucket that stores the pipeline data. Must be globally unique"
  type        = string
  default     = "etl-data-sales-pipeline"
}
