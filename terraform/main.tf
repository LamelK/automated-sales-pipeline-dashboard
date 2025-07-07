provider "aws" {
  region = "us-west-1"
}

######################
# Networking
######################

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}

resource "aws_internet_gateway" "gw" {
  vpc_id = aws_vpc.main.id
}

resource "aws_subnet" "public_1" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.101.0/24"
  map_public_ip_on_launch = true
  availability_zone       = "us-west-1a"
}

resource "aws_subnet" "public_2" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.103.0/24"
  map_public_ip_on_launch = true
  availability_zone       = "us-west-1b"
}

resource "aws_subnet" "private_1" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.102.0/24"
  availability_zone = "us-west-1a"
}

resource "aws_subnet" "private_2" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.104.0/24"
  availability_zone = "us-west-1b"
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.gw.id
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

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "data_bucket" {
  bucket = "etl-data-${random_id.suffix.hex}"
}

resource "aws_s3_object" "raw_data_folder" {
  bucket = aws_s3_bucket.data_bucket.id
  key    = "raw_data/"
  source = "/dev/null"
}

resource "aws_s3_object" "transformed_data_folder" {
  bucket = aws_s3_bucket.data_bucket.id
  key    = "transformed_data/"
  source = "/dev/null"
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.us-west-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = "*"
        Action = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${aws_s3_bucket.data_bucket.bucket}"
      },
      {
        Effect = "Allow"
        Principal = "*"
        Action = ["s3:GetObject", "s3:DeleteObject"]
        Resource = "arn:aws:s3:::${aws_s3_bucket.data_bucket.bucket}/*"
      }
    ]
  })
}

######################
# IAM for Lambda
######################

resource "aws_iam_role" "lambda_role" {
  name = "lambda-s3-access"

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
  name   = "lambda-sg"
  vpc_id = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "rds" {
  name   = "rds-sg"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id, aws_security_group.metabase.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "metabase" {
  name   = "metabase-sg"
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
  name       = "private-subnet-group"
  subnet_ids = [aws_subnet.private_1.id, aws_subnet.private_2.id]
}

resource "aws_db_instance" "etl_database" {
  allocated_storage      = 20
  storage_type           = "gp2"
  engine                 = "mysql"
  engine_version         = "5.7"
  instance_class         = "db.t3.micro"
  db_name                = "electronics_shop"
  username               = "admin"
  password               = random_password.db_password.result
  parameter_group_name   = "default.mysql5.7"
  skip_final_snapshot    = true
  db_subnet_group_name   = aws_db_subnet_group.private.name
  vpc_security_group_ids = [aws_security_group.rds.id]
}

######################
# Lambda Functions
######################

resource "aws_lambda_function" "s3_to_rds" {
  function_name = "s3-to-rds-loader"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.9"
  timeout       = 180
  filename      = "${path.module}/lambda_deployment_package1.zip"

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
      BUCKET_NAME = aws_s3_bucket.data_bucket.bucket
    }
  }
}

resource "aws_lambda_function" "rds_initializer" {
  function_name = "rds-initializer"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_schema_initializer.handler"
  runtime       = "python3.9"
  timeout       = 180
  filename      = "${path.module}/lambda_schema_initializer1.zip"

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
    }
  }
}

######################
# EC2 Metabase
######################

resource "aws_key_pair" "metabase_key" {
  key_name   = "metabase-key"
  public_key = file("${path.module}/metabase.pub")
}

resource "aws_instance" "metabase" {
  ami                         = "ami-0fa9de2bba4d18c53"
  instance_type               = "t3.micro"
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
            curl -O https://downloads.metabase.com/v0.46.6/metabase.jar

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
    Name = "Metabase-Server"
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
