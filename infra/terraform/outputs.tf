output "webhook_url" {
  value = "${aws_apigatewayv2_api.webhook.api_endpoint}/webhook"
}

output "inbound_queue_url" {
  value = aws_sqs_queue.inbound.url
}

output "inbound_dlq_url" {
  value = aws_sqs_queue.inbound_dlq.url
}

output "media_bucket" {
  value = aws_s3_bucket.media.bucket
}

output "worker_policy_arn" {
  value = aws_iam_policy.worker.arn
}
