#!/usr/bin/env python3
"""
Seed DynamoDB table `support_customer_context` with 10 sample items.

Usage:
    python seed_support_context.py
    python seed_support_context.py --table support_customer_context --region us-east-1
    """

import argparse
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3


def build_items():
    now = datetime.now(timezone.utc)

    names = [
        ("C1001", "Aarav"), ("C1002", "Mia"), ("C1003", "Noah"), ("C1004", "Isha"),
        ("C1005", "Liam"), ("C1006", "Ava"), ("C1007", "Ethan"), ("C1008", "Zara"),
        ("C1009", "Arjun"), ("C1010", "Emma"),
    ]
    statuses = ["ACTIVE", "ACTIVE", "ACTIVE", "SUSPENDED", "ACTIVE", "ACTIVE", "ACTIVE", "ACTIVE", "PENDING", "ACTIVE"]
    risk_pool = [["retry_spike"], ["high_contact_rate"], [], ["chargeback_risk"], [], ["retry_spike"], [], ["invoice_dispute"], ["login_risk"], []]
    categories = ["billing", "payments", "invoice", "account_access"]

    items = []
    for i, (customer_id, first_name) in enumerate(names, start=1):
        open_ticket = {
            "ticket_id": f"T-{900 + i}",
            "status": random.choice(["OPEN", "PENDING", "IN_PROGRESS"]),
            "category": random.choice(categories),
            "created_at": (now - timedelta(days=random.randint(1, 15))).isoformat(),
        }

        recent_payments = [
            {
                "payment_id": f"P-{i}-1",
                "status": random.choice(["SUCCESS", "FAILED"]),
                "amount": Decimal(str(round(random.uniform(19.99, 299.99), 2))),
                "currency": "USD",
                "timestamp": (now - timedelta(days=random.randint(1, 20))).isoformat(),
            },
            {
                "payment_id": f"P-{i}-2",
                "status": random.choice(["SUCCESS", "FAILED"]),
                "amount": Decimal(str(round(random.uniform(19.99, 299.99), 2))),
                "currency": "USD",
                "timestamp": (now - timedelta(days=random.randint(1, 20))).isoformat(),
            },
        ]

        item = {
            "customer_id": customer_id,                 # PK (string)
            "first_name": first_name,
            "account_status": statuses[i - 1],
            "risk_flags": risk_pool[i - 1],
            "open_tickets": [open_ticket],
            "recent_payments": recent_payments,
            "updated_at": now.isoformat(),
        }
        items.append(item)

    return items


def seed_table(table_name: str, region: str):
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    items = build_items()

    with table.batch_writer(overwrite_by_pkeys=["customer_id"]) as batch:
        for item in items:
            batch.put_item(Item=item)

    print(f"Seeded {len(items)} items into table '{table_name}' in region '{region}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", default="support_customer_context", help="DynamoDB table name")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    args = parser.parse_args()

    seed_table(args.table, args.region)