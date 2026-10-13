# Postgres 16 on one db.t4g.micro in a private subnet: single-AZ because this is a
# disposable sandbox demo, and Multi-AZ would double the cost for no reviewer-visible
# gain. Encrypted, with 7 days of automated backups and a final snapshot on destroy.
#
# The master password is generated ephemerally and sent write-only, to RDS and to
# Secrets Manager, so it is never in Terraform state. Unlike an RDS-managed secret
# it does not rotate on its own (rotation would break running tasks until they
# restart); bump db_password_version to rotate it, then redeploy.

ephemeral "random_password" "db" {
  length  = 32
  special = false
}

resource "random_id" "final_snapshot" {
  byte_length = 4
}

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier     = local.name
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  db_name             = "xmoney"
  username            = "xmoney"
  password_wo         = ephemeral.random_password.db.result
  password_wo_version = var.db_password_version
  snapshot_identifier = var.restore_snapshot_identifier

  allocated_storage     = 20
  max_allocated_storage = 0
  storage_type          = "gp3"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period    = 7
  backup_window              = "00:00-00:30"
  maintenance_window         = "sun:01:00-sun:01:30"
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true
  deletion_protection        = var.deletion_protection
  skip_final_snapshot        = false
  final_snapshot_identifier  = "${local.name}-final-${random_id.final_snapshot.hex}"

  performance_insights_enabled = false
  apply_immediately            = true

  lifecycle {
    ignore_changes = [snapshot_identifier]
  }
}

resource "aws_rds_instance_state" "main" {
  identifier = aws_db_instance.main.identifier
  state      = var.awake ? "available" : "stopped"
}

resource "aws_secretsmanager_secret" "db" {
  name                    = "${local.name}/db"
  description             = "Postgres master user for ${local.name}. JSON keys: username, password."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
  secret_string_wo = jsonencode({
    username = aws_db_instance.main.username
    password = ephemeral.random_password.db.result
  })
  secret_string_wo_version = var.db_password_version
}

# The secret path segment of the STK callback URL. Daraja sees it in every push,
# so it is low-value, but it keeps strangers from posting fake callbacks.
resource "random_id" "callback_token" {
  byte_length = 16
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${local.name}/stk-callback-token"
  description             = "STK_CALLBACK_TOKEN for ${local.name}."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id     = aws_secretsmanager_secret.app.id
  secret_string = random_id.callback_token.hex
}
