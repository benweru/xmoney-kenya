# Daraja sandbox keys from developer.safaricom.co.ke. Terraform creates the empty
# secret and never sees the value: put it with `aws secretsmanager put-secret-value`
# (docs/runbooks/aws-first-deploy.md), so the keys stay out of Terraform state.
# Only needed when the app stack offers the sandbox rail.
resource "aws_secretsmanager_secret" "daraja" {
  name                    = "${local.name}/daraja-sandbox"
  description             = "Daraja SANDBOX consumer key, secret, shortcode, and passkey. JSON keys: DARAJA_CONSUMER_KEY, DARAJA_CONSUMER_SECRET, DARAJA_SHORTCODE, DARAJA_PASSKEY."
  recovery_window_in_days = 7
}
