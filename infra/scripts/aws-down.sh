#!/usr/bin/env bash
# Destroy the app stack. RDS takes its final snapshot on the way out (Terraform's
# final_snapshot_identifier); `make aws-up SNAPSHOT=<id>` restores from it.
# A stopped RDS instance is started first so the snapshot and delete go cleanly.
set -euo pipefail

cd "$(dirname "$0")/../terraform/app"
db="xmoney-demo"

status=$(aws rds describe-db-instances --db-instance-identifier "$db" \
  --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null || echo "absent")
echo "RDS $db: $status"
if [ "$status" = "stopped" ]; then
  echo "Starting it so it can take a final snapshot..."
  aws rds start-db-instance --db-instance-identifier "$db" >/dev/null
  aws rds wait db-instance-available --db-instance-identifier "$db"
fi

terraform init -input=false -backend-config=../backend.hcl >/dev/null
# awake=true matches the instance state set above, so destroy does not try to stop it.
terraform destroy -var awake=true "$@"

echo
echo "Snapshots kept (restore with: make aws-up SNAPSHOT=<id>):"
aws rds describe-db-snapshots --db-instance-identifier "$db" --snapshot-type manual \
  --query 'reverse(sort_by(DBSnapshots,&SnapshotCreateTime))[].[DBSnapshotIdentifier,SnapshotCreateTime,AllocatedStorage]' \
  --output table
