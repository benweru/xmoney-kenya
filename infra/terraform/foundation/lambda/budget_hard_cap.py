"""Halt running cost drivers when the monthly budget hard cap is crossed.

Does not delete anything. Scales every ECS service to 0, stops leftover tasks,
and stops RDS instances that are in a startable state. ALB, EIPs, and CloudFront
keep billing until a person destroys them.
"""

from __future__ import annotations

import json
import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ecs = boto3.client("ecs")
rds = boto3.client("rds")

STOPPABLE_RDS = frozenset(
    {
        "available",
        "backing-up",
        "modifying",
        "storage-optimization",
        "upgrading",
    }
)


def handler(event, _context):
    logger.info("budget hard cap: %s", json.dumps(event)[:2000])
    result = {"ecs_services": 0, "ecs_tasks": 0, "rds": 0, "errors": []}
    _scale_ecs(result)
    _stop_rds(result)
    if result["errors"]:
        logger.error("completed with errors: %s", result)
    else:
        logger.info("completed: %s", result)
    return result


def _scale_ecs(result: dict) -> None:
    clusters = []
    paginator = ecs.get_paginator("list_clusters")
    for page in paginator.paginate():
        clusters.extend(page.get("clusterArns") or [])

    for cluster in clusters:
        service_arns = []
        paginator = ecs.get_paginator("list_services")
        for page in paginator.paginate(cluster=cluster):
            service_arns.extend(page.get("serviceArns") or [])
        for service in service_arns:
            try:
                ecs.update_service(cluster=cluster, service=service, desiredCount=0)
                result["ecs_services"] += 1
            except ClientError:
                logger.exception("UpdateService failed %s %s", cluster, service)
                result["errors"].append(f"ecs:{service}")

        task_arns = []
        paginator = ecs.get_paginator("list_tasks")
        for page in paginator.paginate(cluster=cluster):
            task_arns.extend(page.get("taskArns") or [])
        for task in task_arns:
            try:
                ecs.stop_task(cluster=cluster, task=task, reason="budget hard cap")
                result["ecs_tasks"] += 1
            except ClientError:
                logger.exception("StopTask failed %s %s", cluster, task)
                result["errors"].append(f"ecs-task:{task}")


def _stop_rds(result: dict) -> None:
    paginator = rds.get_paginator("describe_db_instances")
    for page in paginator.paginate():
        for db in page.get("DBInstances") or []:
            ident = db["DBInstanceIdentifier"]
            status = db.get("DBInstanceStatus", "")
            if status not in STOPPABLE_RDS:
                logger.info("skip RDS %s status=%s", ident, status)
                continue
            try:
                rds.stop_db_instance(DBInstanceIdentifier=ident)
                result["rds"] += 1
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code == "InvalidDBInstanceState":
                    logger.info("RDS %s not stoppable: %s", ident, exc)
                    continue
                logger.exception("StopDBInstance failed %s", ident)
                result["errors"].append(f"rds:{ident}")
