# 003. Hosting on AWS, with Terraform added at the first deploy

- Status: Accepted
- Date: 2026-10-13

## Context

The project needs a public HTTPS URL: Daraja sandbox callbacks have to reach the API, and reviewers need a live demo. The owner is studying for the AWS Solutions Architect Associate (SAA-C03) and wants the hosting to reinforce it. A cheaper platform-as-a-service (Fly.io, Render) would be quicker to set up, but it would not exercise VPCs, IAM, managed databases, or infrastructure as code.

Today nothing is deployed. Local development and CI use docker compose.

## Decision

- **Host on AWS.** The starting design, to be confirmed in a follow-up ADR at the first deploy:
  - API and worker as containers on ECS Fargate behind an Application Load Balancer with an ACM certificate.
  - The web app on the same pattern, or on S3 and CloudFront if it can be exported statically.
  - PostgreSQL 16 on RDS, in private subnets, reachable only from the service security groups.
  - Images in ECR, secrets (Daraja sandbox keys, database credentials) in Secrets Manager or SSM Parameter Store, logs in CloudWatch.
  - One region (`af-south-1` Cape Town for latency to Kenya if its pricing and service coverage hold up, otherwise `eu-west-1`).
- **Terraform later, not now.** Add an `infra/terraform/` module with remote state (S3 with DynamoDB locking, or S3 native locking) in the same milestone as the first deploy. Until then there is nothing to describe, and writing modules ahead of a running service invites drift.
- **Deploys only from CI**, using GitHub Actions OIDC to assume a narrowly scoped IAM role. No long-lived AWS keys in the repo or in GitHub secrets.
- **Guardrails from day one of the account**: an AWS Budgets alert, MFA on the root user, and an IAM user or Identity Center user for daily work.

## Consequences

- More setup than a PaaS, and real costs. The main traps are NAT gateways, idle load balancers, and RDS left running. Mitigations: public subnets with tight security groups or VPC endpoints instead of a NAT gateway, the smallest RDS instance class, and scheduled shutdown of non-demo environments.
- The sandbox rules still apply in AWS: the container sets `SANDBOX_MODE=true`, and the app refuses to start against any Safaricom host except the sandbox.
- The infrastructure becomes reviewable code, which is itself a portfolio artifact.

## Alternatives considered

- **Fly.io or Render with Neon Postgres.** Cheapest and fastest to a public URL, but no AWS learning, and Terraform adds little there.
- **AWS App Runner.** Simpler than ECS, but less control over networking and a narrower feature set; reconsider if ECS proves too heavy.
- **Kubernetes (EKS).** Far more than one API, one worker, and one web app need, and it costs money while idle.
- **Terraform now.** Nothing to apply yet, so it would be untested code.
