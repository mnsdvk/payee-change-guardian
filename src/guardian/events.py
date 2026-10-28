"""Publish case lifecycle events to EventBridge (ops/audit consumers, alarms)."""
from __future__ import annotations

import json
import os


class EventPublisher:
    def __init__(self, client=None, bus: str = ""):
        self._c, self.bus = client, bus or os.environ.get("EVENT_BUS", "default")

    @property
    def client(self):
        if self._c is None:
            import boto3
            self._c = boto3.client("events")
        return self._c

    def publish(self, case: dict) -> None:
        self.client.put_events(Entries=[{
            "Source": "guardian.cases", "DetailType": f"Case{case['state'].title().replace('_', '')}",
            "EventBusName": self.bus,
            "Detail": json.dumps({"case_id": case["case_id"], "state": case["state"],
                                  "vendor": case.get("vendor_name"), "outcome": case.get("outcome", "")}),
        }])
