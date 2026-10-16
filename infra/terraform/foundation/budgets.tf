# Account-wide, not filtered by tag, so a forgotten resource outside Terraform still
# shows up. One email per threshold per month. The $15 hard cap is a separate
# notification (email + SNS) so it can wake the halt Lambda.
resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = format("%.2f", max(concat(var.budget_alerts_usd, [var.budget_hard_cap_usd])...))
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = toset([for v in var.budget_alerts_usd : v if v != var.budget_hard_cap_usd])

    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = "ACTUAL"
      threshold                  = notification.value
      threshold_type             = "ABSOLUTE_VALUE"
      subscriber_email_addresses = [var.alert_email]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = var.budget_hard_cap_usd
    threshold_type             = "ABSOLUTE_VALUE"
    subscriber_email_addresses = [var.alert_email]
    subscriber_sns_topic_arns  = [aws_sns_topic.hard_cap.arn]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "FORECASTED"
    threshold                  = max(var.budget_alerts_usd...)
    threshold_type             = "ABSOLUTE_VALUE"
    subscriber_email_addresses = [var.alert_email]
  }
}
