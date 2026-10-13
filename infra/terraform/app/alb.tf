# The ALB takes HTTP from CloudFront's origin-facing IP ranges only (security
# group), and forwards only requests that carry CloudFront's secret header; anything
# else gets a 403. CloudFront terminates TLS for visitors. The CloudFront-to-ALB hop
# is HTTP because the ALB has no certificate without a custom domain; see
# docs/adr/008-no-nat-gateway.md for that trade-off and the upgrade path.

resource "random_password" "origin_verify" {
  length  = 40
  special = false
}

resource "aws_lb" "api" {
  name                       = local.name
  load_balancer_type         = "application"
  internal                   = false
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  idle_timeout               = 60
}

resource "aws_lb_target_group" "api" {
  name                 = "${local.name}-api"
  vpc_id               = aws_vpc.main.id
  target_type          = "ip"
  port                 = 8000
  protocol             = "HTTP"
  deregistration_delay = 30

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "application/json"
      message_body = "{\"error\":\"forbidden\",\"message\":\"Use the CloudFront URL.\"}"
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener_rule" "from_cloudfront" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [random_password.origin_verify.result]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
