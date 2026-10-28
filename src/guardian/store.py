"""Case store with an audit trail. In-memory for local runs, DynamoDB on AWS."""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Optional


def _now() -> float:
    return time.time()


class InMemoryCaseStore:
    def __init__(self):
        self._c: dict[str, dict] = {}

    def put(self, case: dict) -> None:
        self._c[case["case_id"]] = case

    def get(self, case_id: str) -> Optional[dict]:
        return self._c.get(case_id)

    def list(self) -> list[dict]:
        return sorted(self._c.values(), key=lambda c: c.get("created", 0), reverse=True)

    def clear(self) -> None:
        self._c.clear()

    def find_open_by_phone(self, phone: str) -> Optional[dict]:
        for c in self.list():
            if c.get("state") in ("VERIFYING", "HELD") and c.get("awaiting_phone") == phone:
                return c
        return None

    def find_by_link_token(self, token: str) -> Optional[dict]:
        for c in self.list():
            if token and token in (c.get("link_tokens") or {}).values():
                return c
        return None


def _to_dynamo(o):
    if isinstance(o, float):
        return Decimal(str(o))
    if isinstance(o, dict):
        return {k: _to_dynamo(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_to_dynamo(v) for v in o]
    return o


def _from_dynamo(o):
    if isinstance(o, Decimal):
        return float(o) if o % 1 else int(o)
    if isinstance(o, dict):
        return {k: _from_dynamo(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_from_dynamo(v) for v in o]
    return o


class DynamoCaseStore:
    def __init__(self, table):
        self._t = table

    def put(self, case: dict) -> None:
        self._t.put_item(Item=_to_dynamo(case))

    def get(self, case_id: str) -> Optional[dict]:
        item = self._t.get_item(Key={"case_id": case_id}).get("Item")
        return _from_dynamo(item) if item else None

    def clear(self) -> None:
        keys = [i["case_id"] for i in self._t.scan(ProjectionExpression="case_id").get("Items", [])]
        with self._t.batch_writer() as b:
            for k in keys:
                b.delete_item(Key={"case_id": k})

    def list(self) -> list[dict]:
        items = [_from_dynamo(i) for i in self._t.scan().get("Items", [])]
        return sorted(items, key=lambda c: c.get("created", 0), reverse=True)

    def find_open_by_phone(self, phone: str) -> Optional[dict]:
        for c in self.list():
            if c.get("state") in ("VERIFYING", "HELD") and c.get("awaiting_phone") == phone:
                return c
        return None

    def find_by_link_token(self, token: str) -> Optional[dict]:
        for c in self.list():
            if token and token in (c.get("link_tokens") or {}).values():
                return c
        return None
