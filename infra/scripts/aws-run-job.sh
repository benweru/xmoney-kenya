#!/usr/bin/env bash
# Run one scheduled job now: `make aws-run-job JOB=demo-reset` (seed a fresh demo)
# or JOB=resolve-topups. Waits for the task and prints its exit code.
set -euo pipefail

job=${1:?usage: aws-run-job.sh demo-reset|resolve-topups}
cd "$(dirname "$0")/../terraform/app"
terraform init -input=false -backend-config=../backend.hcl >/dev/null

cluster=$(terraform output -raw ecs_cluster)
family=$(terraform output -json job_task_definitions | jq -er --arg j "$job" '.[$j]')
network=$(terraform output -json job_network | jq -c '{awsvpcConfiguration: {subnets: .subnets, securityGroups: .security_groups, assignPublicIp: "ENABLED"}}')

task=$(aws ecs run-task --cluster "$cluster" --task-definition "$family" \
  --capacity-provider-strategy capacityProvider=FARGATE_SPOT,weight=1 \
  --network-configuration "$network" --query 'tasks[0].taskArn' --output text)
echo "started $task"
aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$task"
code=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task" \
  --query 'tasks[0].containers[0].exitCode' --output text)
echo "$job exited with $code (logs: /ecs/xmoney-demo/jobs, stream prefix $job)"
[ "$code" = "0" ]
