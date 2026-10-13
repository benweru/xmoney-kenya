output "ecr_repository_url" {
  description = "Push the API image here, tagged with the git SHA."
  value       = aws_ecr_repository.api.repository_url
}

output "deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN variable of the GitHub environment."
  value       = aws_iam_role.deploy.arn
}

output "daraja_secret_name" {
  description = "Put the Daraja sandbox keys here before turning on the sandbox rail."
  value       = aws_secretsmanager_secret.daraja.name
}

output "account_id" {
  value = data.aws_caller_identity.current.account_id
}
