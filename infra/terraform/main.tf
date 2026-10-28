locals {
  source_root = "${path.module}/../../backend/src/zapagent"
}

resource "aws_s3_bucket" "media" {
  bucket_prefix = "${var.name}-media-"
}

resource "aws_s3_bucket_public_access_block" "media" {
  bucket                  = aws_s3_bucket.media.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    id     = "expire-media"
    status = "Enabled"

    filter {}

    expiration {
      days = var.media_retention_days
    }
  }
}

resource "aws_sqs_queue" "inbound_dlq" {
  name                      = "${var.name}-inbound-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "inbound" {
  name                       = "${var.name}-inbound"
  visibility_timeout_seconds = 60
  receive_wait_time_seconds  = 10
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.inbound_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

data "archive_file" "webhook" {
  type        = "zip"
  output_path = "${path.module}/build/webhook.zip"

  source {
    content  = file("${local.source_root}/__init__.py")
    filename = "zapagent/__init__.py"
  }

  source {
    content  = file("${local.source_root}/webhook/__init__.py")
    filename = "zapagent/webhook/__init__.py"
  }

  source {
    content  = file("${local.source_root}/webhook/handler.py")
    filename = "zapagent/webhook/handler.py"
  }

  source {
    content  = file("${local.source_root}/webhook/payload.py")
    filename = "zapagent/webhook/payload.py"
  }

  source {
    content  = file("${local.source_root}/webhook/signature.py")
    filename = "zapagent/webhook/signature.py"
  }
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "webhook" {
  name               = "${var.name}-webhook"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "webhook_logs" {
  role       = aws_iam_role.webhook.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "webhook_queue" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.inbound.arn]
  }
}

resource "aws_iam_role_policy" "webhook_queue" {
  name   = "send-to-inbound-queue"
  role   = aws_iam_role.webhook.id
  policy = data.aws_iam_policy_document.webhook_queue.json
}

resource "aws_cloudwatch_log_group" "webhook" {
  name              = "/aws/lambda/${var.name}-webhook"
  retention_in_days = 14
}

resource "aws_lambda_function" "webhook" {
  function_name    = "${var.name}-webhook"
  role             = aws_iam_role.webhook.arn
  runtime          = "python3.12"
  handler          = "zapagent.webhook.handler.handler"
  filename         = data.archive_file.webhook.output_path
  source_code_hash = data.archive_file.webhook.output_base64sha256
  timeout          = 10
  memory_size      = 256

  environment {
    variables = {
      WHATSAPP_APP_SECRET   = var.whatsapp_app_secret
      WHATSAPP_VERIFY_TOKEN = var.whatsapp_verify_token
      INBOUND_QUEUE_URL     = aws_sqs_queue.inbound.url
    }
  }

  depends_on = [aws_cloudwatch_log_group.webhook]
}

resource "aws_apigatewayv2_api" "webhook" {
  name          = "${var.name}-webhook"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "webhook" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.webhook.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "webhook" {
  for_each  = toset(["GET /webhook", "POST /webhook"])
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.webhook.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.webhook.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*/webhook"
}

data "aws_iam_policy_document" "worker" {
  statement {
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueUrl",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.inbound.arn]
  }

  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.media.arn}/*"]
  }
}

resource "aws_iam_policy" "worker" {
  name   = "${var.name}-worker"
  policy = data.aws_iam_policy_document.worker.json
}
