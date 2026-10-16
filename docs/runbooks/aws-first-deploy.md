# Runbook: the first AWS deploy, from a new account to a live demo

This takes a brand-new AWS account to a public demo at `https://<id>.cloudfront.net`. Do the steps in order. Each one ends with a check. The design is in [ADR 007](../adr/007-aws-iam-design.md) (IAM) and [ADR 008](../adr/008-no-nat-gateway.md) (network), and the running costs are in [aws-costs.md](aws-costs.md).

> **Costs start at step 5.** Awake, the app stack costs roughly $1.50–2 a day. Steps 1–4 cost cents a month. When you are not demoing, run `make aws-sleep` or `make aws-down`.

Nothing here touches real money. The API refuses to start unless `SANDBOX_MODE=true`, and it refuses every Safaricom host except `sandbox.safaricom.co.ke`.

## 0. What you need on your laptop

| Tool | Version | Check |
| --- | --- | --- |
| AWS CLI | v2 | `aws --version` |
| Terraform | 1.11 or newer (CI uses 1.16.5) | `terraform version` |
| Docker | any recent | `docker info` |
| jq | any | `jq --version` |
| GitHub CLI, signed in to the repo | any | `gh auth status` |
| tflint (optional, for `make tf-check`) | 0.64 | `tflint --version` |

Clone the repo and work from its root on an up-to-date `main`.

## 1. Create and harden the AWS account

All of this is in the AWS console, signed in as the **root user**. It is the last time you use root.

1. **Create the account** at [aws.amazon.com](https://aws.amazon.com/) with an email address only you control (for example `you+aws@…`). Add a payment card. If sign-up asks you to choose between a free plan and a paid plan, check that the plan includes ECS Fargate, RDS, Elastic Load Balancing, CloudFront, EventBridge Scheduler, Secrets Manager, and Budgets. If the free plan restricts any of them, pick the paid plan; credits still apply to it.
2. **Turn on MFA for root.** Account menu (top right) → **Security credentials** → **Multi-factor authentication (MFA)** → **Assign MFA device**. Use a passkey or an authenticator app. Then register a second device (a hardware key or a second phone) so losing one does not lock you out.
   - Check: the same page shows two MFA devices and **no access keys** under "Access keys". If there are any root access keys, delete them.
3. **Let IAM identities see billing.** Account menu → **Account** → "IAM user and role access to Billing information" → **Edit** → tick **Activate IAM Access** → **Update**. Without this, your admin user in step 2 cannot see Budgets or Cost Explorer.
4. **Turn on cost alerts.** **Billing and Cost Management** → **Billing preferences**:
   - **Alert preferences** → **Edit** → tick **Receive AWS Free Tier alerts** and enter your email.
   - **Invoice delivery preferences** → make sure PDF invoices go to your email.
5. **Turn on Cost Explorer.** **Billing and Cost Management** → **Cost Explorer** → **Launch Cost Explorer**. It takes up to 24 hours to fill with data.
6. **Optional: alternate contacts.** Account menu → **Account** → **Alternate contacts** → set Billing and Security to your email, so AWS security notices reach you.
7. **Pick the region:** `eu-west-1` (Ireland), which is what the Terraform uses by default. `af-south-1` (Cape Town) is closer to Kenya, but it is an opt-in region with higher prices. To use it, enable it under Account → AWS Regions, and pass `region` to all three stacks.

## 2. Create your everyday admin identity (IAM Identity Center)

Still as root, with the region selector set to **Europe (Ireland) eu-west-1**:

1. Open **IAM Identity Center** → **Enable**. Choose **Enable with AWS Organizations** when offered. That creates an organization with this account as its management account, which is free.
2. **Require MFA.** **Settings** → **Authentication** → **Multi-factor authentication** → **Configure**:
   - Prompt users for MFA: **Every time they sign in**.
   - If a user does not yet have a registered MFA device: **Require them to register an MFA device at sign in**.
3. **Create your user.** **Users** → **Add user**: username `ben`, your email, first and last name → **Add user**. Accept the invitation email, set a password, and register an MFA device.
4. **Create a permission set.** **Permission sets** → **Create permission set** → **Predefined permission set** → **AdministratorAccess** → session duration **4 hours** → **Create**.
5. **Assign it.** **AWS accounts** → tick your account → **Assign users or groups** → `ben` → **AdministratorAccess** → **Submit**.
6. Copy the **AWS access portal URL** from the Identity Center **Dashboard** (it looks like `https://d-xxxxxxxxxx.awsapps.com/start`).
7. **Sign out of root.** From here on, sign in through the access portal as `ben`.

### Configure the CLI

```bash
aws configure sso
#   SSO session name:          xmoney
#   SSO start URL:             https://d-xxxxxxxxxx.awsapps.com/start
#   SSO region:                eu-west-1
#   SSO registration scopes:   (press Enter for the default)
#   -> a browser opens; approve, then pick the account and AdministratorAccess
#   CLI default client Region: eu-west-1
#   CLI default output format: json
#   Profile name:              xmoney

export AWS_PROFILE=xmoney     # every later command assumes this
aws sts get-caller-identity
```

Check: the ARN contains `AWSReservedSSO_AdministratorAccess`, not `root`. When the session expires, run `aws sso login` again.

## 3. Bootstrap the Terraform state bucket

```bash
make aws-bootstrap
```

Review the plan: **8 to add**:

- the `xmoney-tfstate-<account id>` bucket, with its versioning, encryption, public access block, ownership controls, lifecycle rule, and TLS-only bucket policy;
- `local_file.backend_config`.

Type `yes`.

Check: `cat infra/terraform/backend.hcl` shows the bucket name, `use_lockfile = true`, and `encrypt = true`. That file and `infra/terraform/bootstrap/terraform.tfstate` are gitignored. Keep the state file. If you lose it, `terraform import aws_s3_bucket.state <bucket>` recovers it.

## 4. Apply the foundation stack (alerts, registry, deploy role, Daraja secret)

```bash
cp infra/terraform/foundation/terraform.tfvars.example infra/terraform/foundation/terraform.tfvars
# edit: alert_email = "you@example.com"
make aws-foundation
```

Review the plan: the budget `xmoney-demo-monthly` (alerts at $5/$10/$20 plus a **$15 hard cap**), the ECR repository `xmoney-demo/api` and its lifecycle policy, the GitHub OIDC provider, the role `xmoney-demo-github-deploy` and its ECR policy, the secret `xmoney-demo/daraja-sandbox`, and the hard-cap IAM/SNS/Lambda pieces. Type `yes`.

If the apply fails with `EntityAlreadyExists` on the OIDC provider, the account already has one. Set `create_github_oidc_provider = false` and apply again.

Checks:

- **Billing and Cost Management → Budgets** shows `xmoney-demo-monthly` with alerts at $5, $10, and $20 actual, plus $20 forecast, and an automatic action at $15 actual. That action cannot be an SCP on this account; see [aws-costs.md](aws-costs.md).
- `terraform -chdir=infra/terraform/foundation output` prints `ecr_repository_url`, `deploy_role_arn`, and `daraja_secret_name`.

### Optional: put the Daraja sandbox keys in Secrets Manager

Skip this if the demo only offers the mock rail, which is the default. To offer **Safaricom's Daraja sandbox** next to the mock, get the keys from [developer.safaricom.co.ke](https://developer.safaricom.co.ke) (see [daraja-sandbox-top-up.md](daraja-sandbox-top-up.md)). Then write them from a file, so they stay out of your shell history:

```bash
umask 077
cat > /tmp/daraja.json <<'EOF'
{"DARAJA_CONSUMER_KEY":"...","DARAJA_CONSUMER_SECRET":"...","DARAJA_SHORTCODE":"174379","DARAJA_PASSKEY":"..."}
EOF
aws secretsmanager put-secret-value --secret-id xmoney-demo/daraja-sandbox --secret-string file:///tmp/daraja.json
rm -P /tmp/daraja.json 2>/dev/null || shred -u /tmp/daraja.json
```

Check: `aws secretsmanager describe-secret --secret-id xmoney-demo/daraja-sandbox --query VersionIdsToStages` shows one `AWSCURRENT` version. Never print the value.

## 5. Push the first API image

The app stack's task definitions need an image to exist. Later images come from GitHub Actions.

```bash
REPO=$(terraform -chdir=infra/terraform/foundation output -raw ecr_repository_url)
TAG=$(git rev-parse HEAD)
aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO%%/*}"
docker build --platform linux/amd64 -t "$REPO:$TAG" api     # amd64 even on Apple Silicon
docker push "$REPO:$TAG"
```

Check: `aws ecr describe-images --repository-name xmoney-demo/api --query 'imageDetails[].imageTags'` lists `$TAG`. Scan-on-push results appear under the image in the ECR console.

## 6. Apply the app stack (this is where costs start)

```bash
cp infra/terraform/app/terraform.tfvars.example infra/terraform/app/terraform.tfvars
# For the sandbox rail: enable_sandbox_rail = true and sandbox_allowed_phones = ["+2547XXXXXXXX"]
make aws-plan TAG=$TAG
```

Read the plan before you apply. It should add 66 resources, and you should confirm:

- There is **no** `aws_nat_gateway`, and no `aws_eip`.
- `aws_db_instance.main` is `db.t4g.micro`, `multi_az = false`, `publicly_accessible = false`, and `storage_encrypted = true`. The password shows as write-only, not as a value.
- `aws_ecs_service.api` has `desired_count = 1`.
- `aws_lb_listener.http` has a default action of `fixed-response` 403.
- The `aws_scheduler_schedule` resources `resolve-topups` and `demo-reset` are `ENABLED`.

```bash
make aws-up TAG=$TAG
```

It takes 10–20 minutes, mostly RDS and CloudFront. When it finishes:

```bash
terraform -chdir=infra/terraform/app output public_url    # https://dxxxxxxxxxxxx.cloudfront.net
URL=$(terraform -chdir=infra/terraform/app output -raw public_url)
```

The API task starts once RDS is available and runs the migrations. Watch it in **ECS → Clusters → xmoney-demo → Services → api → Logs**, or:

```bash
aws logs tail /ecs/xmoney-demo/api --follow     # expect "Uvicorn running on http://0.0.0.0:8000"
```

## 7. Seed the demo

```bash
make aws-run-job JOB=demo-reset
```

This runs the same task the nightly schedule runs. It exits 0, and the jobs log shows `reset the demo to its seed`. The wallets @amina, @baraka, and @wanjiku now exist with some history, and none of them has a PIN.

## 8. Connect GitHub Actions

1. **Create the environment.** GitHub → repo **Settings** → **Environments** → **New environment** `demo`:
   - **Deployment branches and tags** → **Selected branches and tags** → add `main`.
   - Optional: **Required reviewers** → yourself, so every deploy waits for a click.
2. **Set two repository variables.** They are variables, not secrets, because neither is sensitive, and the workflow reads them before it enters the environment.

   ```bash
   gh variable set AWS_DEPLOY_ROLE_ARN --body "$(terraform -chdir=infra/terraform/foundation output -raw deploy_role_arn)"
   gh variable set AWS_REGION --body eu-west-1
   ```

3. **Run the first deploy.** **Actions** → **Deploy demo** → **Run workflow** on `main`. It rebuilds the image at `main`'s SHA, rolls the API, repoints the schedules, uploads the wallet to S3, and invalidates CloudFront. Every later merge to `main` deploys the same way.

   Check: the run ends with `live at https://….cloudfront.net`.

## 9. Verify

```bash
curl -fsS "$URL/api/health"                                   # 200 and a JSON status
curl -fsS -o /dev/null -w '%{http_code}\n' "$URL/"           # 200 (the wallet)
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$URL/api/v1/sandbox/journal-entries" \
  -H 'content-type: application/json' -d '{}'                # 404: minting is off
curl -s -o /dev/null -w '%{http_code}\n' -X PUT "$URL/api/sandbox/daraja/__control/behavior" \
  -H 'content-type: application/json' -d '{"outcome":"cancelled"}'   # 404: mock control is off
ALB=$(aws elbv2 describe-load-balancers --names xmoney-demo --query 'LoadBalancers[0].DNSName' --output text)
curl -m 5 -s -o /dev/null -w '%{http_code}\n' "http://$ALB/health" || echo "blocked (good)"
```

The last command must time out or return 403. The ALB answers only CloudFront.

Then test it on a phone:

1. Open `$URL`, register, and sign in with the code from the sandbox inbox panel.
2. Top up KES 100 on the **Mock** rail. Use a number ending `000` to succeed, or `032` to see a cancellation.
3. Send KES 50 to `@amina` and check that her name is confirmed before you send.
4. Open History.
5. Try a top-up above KES 1,000. It is refused, because the demo cap is `topup_max_kes`.
6. If you enabled the sandbox rail: switch to **Daraja sandbox**, top up KES 1 to an allowed phone, and approve the prompt. That is M2's "a sandbox top-up works from the live site". A phone that is not on the list gets "only prompts the demo owner's test phones".

Finally, tag your costs. **Billing and Cost Management → Cost allocation tags** → activate `project` and `env`. They appear up to 24 hours after the first tagged resource exists. Cost Explorer can then filter by `project = xmoney-kenya`.

## Later changes

- **Code:** merge to `main`. The workflow deploys it.
- **Infrastructure** (for example, `topup_max_kes` or the sandbox rail): edit `infra/terraform/app/terraform.tfvars`, run `make aws-plan`, then `make aws-up`. The ECS service and the schedules ignore Terraform's task-definition revisions, so that deploys can own them. Run **Deploy demo** once afterwards so the containers pick up the new settings.
- **Rotate the database password:** bump `db_password_version` in tfvars, `make aws-up`, then run **Deploy demo**.
- **Pause or tear down:** see [aws-costs.md](aws-costs.md).

## If it does not work

| Symptom | Likely cause and fix |
| --- | --- |
| `make aws-foundation` says the backend bucket does not exist | Step 3 did not finish, or `AWS_PROFILE` points at a different account. Check with `aws sts get-caller-identity`. |
| `ExpiredToken` / `The SSO session has expired` | `aws sso login` |
| App plan fails on `data.aws_ecr_image.latest` | No image pushed yet. Do step 5, or pass `TAG=`. |
| ECS task stops with `ResourceInitializationError: unable to pull secrets` | The sandbox rail is on but the Daraja secret has no value (step 4), or a JSON key name is wrong. |
| ECS task stops with `CannotPullContainerError` | The image tag is not in ECR, or it was built for arm64. Rebuild with `--platform linux/amd64`. |
| API log: `Refusing to start: a public demo with the sandbox rail must set DARAJA_SANDBOX_ALLOWED_PHONES` | Set `sandbox_allowed_phones` in tfvars. |
| `$URL/api/...` returns 502/503 | The API task is not healthy yet, or RDS is stopped (`make aws-wake`). Check the service events in the ECS console. |
| `$URL/api/...` returns 403 `Use the CloudFront URL` | The CloudFront and ALB header secrets are out of step. Run `make aws-up` again. |
| Deploy workflow is **skipped** | `AWS_DEPLOY_ROLE_ARN` is not a repository variable (an environment variable is not visible to the job's `if`). |
| Deploy fails with `Not authorized to perform sts:AssumeRoleWithWebIdentity` | The job is not running in the `demo` environment, or the repository name differs from `github_repository`. |
| Deploy fails with `AccessDenied` on one action | A missing permission. Add that one action to `infra/terraform/app/deploy.tf` (ADR 007), then `make aws-up`. |
| Visitors get `429 rate_limited` | That is working as designed ([ADR 006](../adr/006-open-demo-protections.md)). The counters reset every window. |
