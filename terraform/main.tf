provider "aws" {
  region = var.aws_region
}

######################
# Networking
######################

locals {
  # Derived from the region rather than a DescribeAvailabilityZones call,
  # which some AWS Organizations deny through a service control policy.
  azs = ["${var.aws_region}a", "${var.aws_region}b"]
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "sales-pipeline-vpc"
  }
}

resource "aws_internet_gateway" "gw" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "sales-pipeline-igw"
  }
}

resource "aws_subnet" "public_1" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 101)
  map_public_ip_on_launch = true
  availability_zone       = local.azs[0]

  tags = {
    Name = "sales-pipeline-public-1"
  }
}

resource "aws_subnet" "public_2" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 103)
  map_public_ip_on_launch = true
  availability_zone       = local.azs[1]

  tags = {
    Name = "sales-pipeline-public-2"
  }
}

resource "aws_subnet" "private_1" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 102)
  availability_zone = local.azs[0]

  tags = {
    Name = "sales-pipeline-private-1"
  }
}

resource "aws_subnet" "private_2" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 104)
  availability_zone = local.azs[1]

  tags = {
    Name = "sales-pipeline-private-2"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.gw.id
  }

  tags = {
    Name = "sales-pipeline-public-rt"
  }
}

resource "aws_route_table_association" "public_assoc_1" {
  subnet_id      = aws_subnet.public_1.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_assoc_2" {
  subnet_id      = aws_subnet.public_2.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "sales-pipeline-private-rt"
  }
}

resource "aws_route_table_association" "private_assoc_1" {
  subnet_id      = aws_subnet.private_1.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_assoc_2" {
  subnet_id      = aws_subnet.private_2.id
  route_table_id = aws_route_table.private.id
}

######################
# S3
######################

resource "aws_s3_bucket" "data_bucket" {
  bucket = var.bucket_prefix
}

resource "aws_s3_object" "raw_data_folder" {
  bucket  = aws_s3_bucket.data_bucket.id
  key     = "raw_data/"
  content = ""
}

resource "aws_s3_object" "transformed_data_folder" {
  bucket  = aws_s3_bucket.data_bucket.id
  key     = "transformed_data/"
  content = ""
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = "*"
        Action    = ["s3:ListBucket"]
        Resource  = "arn:aws:s3:::${aws_s3_bucket.data_bucket.bucket}"
      },
      {
        Effect    = "Allow"
        Principal = "*"
        Action    = ["s3:GetObject", "s3:DeleteObject"]
        Resource  = "arn:aws:s3:::${aws_s3_bucket.data_bucket.bucket}/*"
      }
    ]
  })
}

######################
# IAM for Lambda
######################

resource "aws_iam_role" "lambda_role" {
  name = "sales-pipeline-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_s3" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
}

resource "aws_iam_role_policy_attachment" "lambda_vpc_access" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}


######################
# Security Groups
######################

resource "aws_security_group" "lambda" {
  name   = "sales-pipeline-lambda-sg"
  vpc_id = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "rds" {
  name   = "sales-pipeline-rds-sg"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id, aws_security_group.metabase.id]
  }

  ingress {
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = ["${var.allowed_ip}/32"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "metabase" {
  name   = "sales-pipeline-metabase-sg"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

######################
# RDS
######################

resource "random_password" "db_password" {
  length  = 16
  special = false
}

resource "aws_db_subnet_group" "private" {
  name       = "sales-pipeline-db-subnets"
  subnet_ids = [aws_subnet.public_1.id, aws_subnet.public_2.id]
}

resource "aws_db_instance" "etl_database" {
  identifier             = "electronics-shop-db"
  allocated_storage      = 20
  storage_type           = "gp2"
  engine                 = "mysql"
  engine_version         = "5.7"
  instance_class         = var.db_instance_type
  db_name                = var.db_name
  username               = var.db_username
  password               = random_password.db_password.result
  parameter_group_name   = "default.mysql5.7"
  publicly_accessible    = true
  skip_final_snapshot    = true
  db_subnet_group_name   = aws_db_subnet_group.private.name
  vpc_security_group_ids = [aws_security_group.rds.id]
}

######################
# Lambda Functions
######################

resource "aws_lambda_function" "s3_to_rds" {
  function_name    = "sales-pipeline-loader"
  role             = aws_iam_role.lambda_role.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.9"
  timeout          = 180
  filename         = "${path.module}/lambda_deployment_package1.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda_deployment_package1.zip")

  vpc_config {
    subnet_ids         = [aws_subnet.private_1.id, aws_subnet.private_2.id]
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      RDS_HOST     = aws_db_instance.etl_database.address
      RDS_USER     = aws_db_instance.etl_database.username
      RDS_PASSWORD = random_password.db_password.result
      RDS_DB       = aws_db_instance.etl_database.db_name
      BUCKET_NAME  = aws_s3_bucket.data_bucket.bucket
    }
  }
}

######################
# EC2 Metabase
######################

resource "aws_key_pair" "metabase_key" {
  key_name   = var.ec2_key_name
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "aws_instance" "metabase" {
  ami                         = "ami-06fb1802e2b757f09"
  instance_type               = var.ec2_instance_type
  subnet_id                   = aws_subnet.public_1.id
  vpc_security_group_ids      = [aws_security_group.metabase.id]
  associate_public_ip_address = true
  key_name                    = aws_key_pair.metabase_key.key_name

  user_data = <<-EOF
            #!/bin/bash
            # Update and install dependencies
            sudo apt update -y
            sudo apt install -y openjdk-21-jdk curl

            # Download Metabase
            curl -fL -o metabase.jar https://downloads.metabase.com/v0.64.1/metabase.jar

            # Create 2GB swap file
            sudo fallocate -l 2G /swapfile
            sudo chmod 600 /swapfile
            sudo mkswap /swapfile
            sudo swapon /swapfile
            echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

            # Run Metabase
            nohup java -jar metabase.jar > metabase.log 2>&1 &
            EOF

  tags = {
    Name = "sales-pipeline-metabase"
  }
}

######################
# Outputs
######################

output "s3_bucket_name" {
  value = aws_s3_bucket.data_bucket.bucket
}

output "metabase_public_ip" {
  value = aws_instance.metabase.public_ip
}

output "rds_endpoint" {
  value = aws_db_instance.etl_database.endpoint
}

output "db_password" {
  value     = random_password.db_password.result
  sensitive = true
}

output "ssh_command" {
  value       = "ssh -i ~/.ssh/metabase ubuntu@${aws_instance.metabase.public_ip}"
  description = "SSH command to connect to Metabase EC2"
}
