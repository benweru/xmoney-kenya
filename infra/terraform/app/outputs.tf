output "public_url" {
  description = "The demo. The API is under /api."
  value       = local.public_url
}

output "stk_callback_base" {
  description = "PUBLIC_BASE_URL the API gives Daraja for callbacks."
  value       = local.api_url
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.web.id
}

output "web_bucket" {
  value = aws_s3_bucket.web.id
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "db_identifier" {
  value = aws_db_instance.main.identifier
}

output "job_task_definitions" {
  description = "Run one by hand with make aws-run-job JOB=demo-reset."
  value       = { for name, job in aws_ecs_task_definition.job : name => job.family }
}

output "job_network" {
  description = "Subnets and security group for one-off job tasks."
  value = {
    subnets         = aws_subnet.public[*].id
    security_groups = [aws_security_group.tasks.id]
  }
}

output "deploy_parameter" {
  value = aws_ssm_parameter.deploy.name
}
