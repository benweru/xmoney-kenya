# 008. AWS network: no NAT gateway, tasks in public subnets, CloudFront in front

- Status: Accepted
- Date: 2026-10-13

## Context

The usual AWS reference layout runs containers in private subnets and sends their outbound traffic through a NAT gateway. A NAT gateway costs about $0.045 an hour (around $33 a month) per AZ before data charges. That is more than the rest of this demo combined. The demo still needs outbound access to ECR, Secrets Manager, CloudWatch Logs, and the Daraja sandbox. It also needs one public HTTPS URL for visitors and Daraja callbacks, without buying a domain.

## Decision

- **Two AZs, no NAT gateway.** Public subnets hold the ALB and the Fargate tasks. Tasks get public IPs, so they reach the internet through the internet gateway. Private subnets hold only RDS and have no route out.
- **Security groups do the locking down instead of the subnet:**
  - The tasks' security group allows inbound port 8000 only from the ALB's security group.
  - Outbound, tasks may use 443 to anywhere and 5432 only to the database security group. Nothing else.
  - RDS accepts 5432 only from the tasks' security group.
  - The default security group has no rules.
- **The ALB accepts only CloudFront.** Its security group allows port 80 only from the managed prefix list `com.amazonaws.global.cloudfront.origin-facing`. Its listener forwards only requests carrying a secret `X-Origin-Verify` header that CloudFront adds. Everything else gets a 403, including other CloudFront distributions, which share the same IP ranges.
- **CloudFront serves everything on one domain:**
  - The default behavior serves the static wallet from a private S3 bucket through Origin Access Control.
  - `/api/*` goes to the ALB with caching off and all viewer headers and cookies forwarded. A CloudFront Function strips the `/api` prefix.
  - Visitors and Daraja use `https://<id>.cloudfront.net`. Session cookies are same-origin, so there is no CORS.
  - The API counts 2 trusted proxy hops in `X-Forwarded-For` (CloudFront and the ALB) when it reads the client IP for rate limits.

## Consequences

- **CloudFront to the ALB is HTTP.** An ALB needs an ACM certificate for a name it owns, and the demo has no custom domain. Traffic between CloudFront and the region crosses AWS's network, and the ALB is unreachable except from CloudFront with the header. Session cookies still cross that hop in clear text, which is acceptable for sandbox-only test data and not for production. The upgrade path:
  1. Buy a domain.
  2. Put an ACM certificate on the ALB.
  3. Switch the origin to `https-only`.
  4. Optionally, move the ALB into private subnets behind a CloudFront VPC origin.
- Each task's public IP is billed (about $3.65 a month per IPv4 address), and so are the ALB's two addresses. That is still far cheaper than NAT. [aws-costs.md](../runbooks/aws-costs.md) itemizes it.
- Tasks could be reached directly if their security group were loosened by mistake. Terraform owns the rules, and the only inbound rule references the ALB's security group.
- RDS cannot reach the internet, so it cannot be a data-exfiltration path, and it needs no internet access anyway.
- Unknown web paths return S3's XML 404, not the app's `404.html`. CloudFront error pages apply to every behavior, so they would rewrite the API's JSON 404s too.

## Alternatives considered

- **Private subnets and a NAT gateway.** The textbook layout, and the right one in production. It costs about $33 a month or more per AZ, which is too much for an idle portfolio demo.
- **Private subnets and VPC interface endpoints** for ECR, Secrets Manager, and Logs. Each endpoint costs about $7 a month per AZ, so four or more of them cost as much as NAT, and the Daraja sandbox would still need a way out.
- **A NAT instance (t4g.nano).** Cheap, but it is a server to patch and a single point of failure, and it is not what a reviewer expects to see.
- **No ALB (CloudFront to a task's public IP).** Task IPs change on every deploy, and there would be no health checks.
