# Runbook: what the AWS demo costs, and how to sleep, wake, and tear it down

The demo has three states. Pick one deliberately, because the Budgets alerts at $5, $10, and $20 a month **will** fire if the app stack stays awake.

| State | Command | About a day | About a month | Back to awake |
| --- | --- | --- | --- | --- |
| Awake | `make aws-up` / `make aws-wake` | $1.90 | $57 | — |
| Asleep | `make aws-sleep` | $1.00 | $30 | `make aws-wake`, about 5–10 minutes |
| Down | `make aws-down` | $0.03 | $1 | `make aws-up SNAPSHOT=<id>`, about 15–20 minutes |

**Rule of thumb:** keep it down, bring it up for a demo or an interview, and take it down again afterwards. Sleep only saves about half, because the ALB and its IP addresses keep billing, so it is only worth it for a pause of a day or two.

## Where the money goes

These are estimates from `eu-west-1` on-demand list prices, for a month of 730 hours. Prices change, so check the [AWS Pricing Calculator](https://calculator.aws/) and **Cost Explorer** filtered by `project = xmoney-kenya`. New accounts usually start with AWS credits (see **Billing → Credits**), which absorb these charges until they run out.

| Item | Awake | Asleep | Down |
| --- | --- | --- | --- |
| Application Load Balancer, hourly | $18.40 | $18.40 | — |
| ALB's two public IPv4 addresses ($0.005 an hour each) | $7.30 | $7.30 | — |
| ALB capacity units at demo traffic | under $1 | — | — |
| API task: Fargate, 0.25 vCPU and 0.5 GB | $9.00 | — | — |
| API task's public IPv4 address | $3.65 | — | — |
| RDS `db.t4g.micro`, single-AZ | $13 | — (stopped) | — |
| RDS storage, 20 GB gp3 | $2.55 | $2.55 | — |
| RDS final snapshot after `aws-down` (billed on data used) | — | — | under $0.50 |
| Scheduled jobs (Fargate Spot, about 73 task-hours, plus their IPs) | $0.70 | — (paused) | — |
| Secrets Manager: db, callback token, Daraja ($0.40 each) | $1.20 | $1.20 | $0.40 |
| CloudWatch Logs (14-day retention) | under $0.50 | — | — |
| ECR (10 images kept) | $0.10 | $0.10 | $0.10 |
| CloudFront (the always-free tier covers 1 TB and 10M requests) | $0 | $0 | — |
| S3 (state and web files), Budgets (2 free), Scheduler | cents | cents | cents |

There is no NAT gateway, which would add about $33 a month per AZ ([ADR 008](../adr/008-no-nat-gateway.md)).

## Sleep: `make aws-sleep`

This applies the app stack with `awake = false`, which:

- sets the API service to 0 tasks;
- stops the RDS instance (`aws_rds_instance_state`);
- disables both schedules, so no jobs run against a stopped database.

The URL serves the wallet's static files, but every API call returns 503 until you wake it.

```bash
export AWS_PROFILE=xmoney
make aws-sleep          # review: desired_count 1 -> 0, state ENABLED -> DISABLED, instance stopped
make aws-wake           # the reverse; RDS takes a few minutes to become available
```

**RDS starts itself after 7 days stopped.** That is an AWS rule. If you sleep longer, either run `make aws-sleep` again each week (Terraform sees the instance running and stops it again) or use `make aws-down`.

Check that it is asleep:

```bash
aws ecs describe-services --cluster xmoney-demo --services api --query 'services[0].[desiredCount,runningCount]'
aws rds describe-db-instances --db-instance-identifier xmoney-demo --query 'DBInstances[0].DBInstanceStatus'
```

Expect `[0, 0]` and `"stopped"`.

## Down: `make aws-down`

`infra/scripts/aws-down.sh` does three things:

1. If RDS is stopped, it starts it, so the final snapshot and the delete go through cleanly.
2. It runs `terraform destroy` on the app stack. RDS takes a final snapshot named `xmoney-demo-final-<random>` before it is deleted. The web bucket is emptied and deleted. CloudFront takes the longest, often 5–15 minutes.
3. It lists the manual snapshots you can restore from.

Foundation stays: Budgets, ECR images, the deploy role, and the Daraja secret. The GitHub deploy workflow then fails at "Read the app stack's deploy config". To stop it running on merges in the meantime, delete the `AWS_DEPLOY_ROLE_ARN` repository variable, and the workflow is skipped instead.

Check that it is down: `terraform -chdir=infra/terraform/app state list` prints nothing, and **Cost Explorer** shows the daily cost dropping to cents within a day or two.

## Up again: `make aws-up`

```bash
make aws-up                                   # empty database; then: make aws-run-job JOB=demo-reset
make aws-up SNAPSHOT=xmoney-demo-final-1a2b3c4d   # restore the last database
```

New task definitions use the most recently pushed image, unless you pass `TAG=<sha>`. Run **Actions → Deploy demo** afterwards to upload the wallet again, because the bucket was deleted. The CloudFront URL is new after every `aws-down`/`aws-up`. The deploy workflow reads the new URL from SSM, so nothing in GitHub changes. Old snapshots cost storage, so delete the ones you no longer need:

```bash
aws rds delete-db-snapshot --db-snapshot-identifier <id>
```

## If a budget alert arrives

1. Open **Cost Explorer**. Group by **Service**, filter `project = xmoney-kenya`, and set the granularity to **Daily**.
2. If the cost is the ALB, RDS, or Fargate, the app stack is awake. Run `make aws-down` unless you are demoing.
3. If a service appears that this stack does not use (for example EC2 instances, NAT gateways, or another region), something was created outside Terraform. Find it with **Billing → Bills → Charges by service** and delete it.
4. If the forecast alert fires early in the month, that means "at this rate you will pass $20". It is the earliest warning, so act on it.
