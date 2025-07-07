### ✅ variables.tf

variable "aws_region" {
  description = "The AWS region to deploy into"
  type        = string
  default     = "us-west-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the public subnet"
  type        = string
  default     = "10.0.1.0/24"
}

variable "private_subnet_cidr" {
  description = "CIDR block for the private subnet"
  type        = string
  default     = "10.0.2.0/24"
}

variable "db_instance_type" {
  description = "Instance type for RDS"
  type        = string
  default     = "db.t3.micro"
}

variable "ec2_instance_type" {
  description = "Instance type for Metabase EC2"
  type        = string
  default     = "t3.micro"
}

variable "ec2_key_name" {
  description = "Name of the SSH key pair for EC2"
  type        = string
  default     = "metabase-key"
}

variable "ssh_public_key_path" {
  description = "Path to your SSH public key"
  type        = string
  default     = "~/.ssh/metabase.pub"
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
  description = "Prefix for the S3 bucket name"
  type        = string
  default     = "etl-data"
}
