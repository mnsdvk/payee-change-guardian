#!/usr/bin/env python3
"""Seed the trusted vendor registry with SYNTHETIC vendors.

The registered phone is YOUR test phone (or a number you control). It is read from the
environment so no personal data lands in the repo:

  VENDORS_TABLE=<stack output> DEMO_PHONE=+15551234567 APPROVER_EMAIL=you@example.com \
      SUPPLIER_EMAIL=a-verified-address-you-control@example.com \
      python scripts/seed_vendors.py
"""
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import boto3  # noqa: E402
from guardian.demo_data import vendors  # noqa: E402

table = boto3.resource("dynamodb").Table(os.environ["VENDORS_TABLE"])
phone = os.environ["DEMO_PHONE"]
for v in vendors(whatsapp=phone, sms=phone, approver=os.environ["APPROVER_EMAIL"],
                 supplier_email=os.environ.get("SUPPLIER_EMAIL", os.environ["APPROVER_EMAIL"])):
    table.put_item(Item={k: (str(x) if isinstance(x, float) else x)
                         for k, x in v.to_dict().items()} | {"typical_amount": int(v.typical_amount)})
    print("seeded", v.vendor_id)
