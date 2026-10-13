output "state_bucket" {
  description = "Holds foundation.tfstate and app.tfstate."
  value       = aws_s3_bucket.state.id
}

output "backend_config_file" {
  description = "Pass to terraform init -backend-config in the other stacks."
  value       = abspath(local_file.backend_config.filename)
}
