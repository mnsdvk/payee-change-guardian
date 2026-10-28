"""Trusted vendor registry. The only source of verification contacts."""
from __future__ import annotations

from typing import Optional, Protocol

from .models import ChangeRequest, Vendor


class Registry(Protocol):
    def get(self, vendor_id: str) -> Optional[Vendor]: ...
    def all(self) -> list[Vendor]: ...
    def update_bank(self, vendor_id: str, account: str, bank: str) -> None: ...


class InMemoryRegistry:
    def __init__(self, vendors: list[Vendor]):
        self._v = {v.vendor_id: v for v in vendors}

    def get(self, vendor_id):
        return self._v.get(vendor_id)

    def all(self):
        return list(self._v.values())

    def update_bank(self, vendor_id, account, bank):
        v = self._v[vendor_id]
        v.bank_account = account
        if bank:
            v.bank_name = bank


class DynamoRegistry:
    def __init__(self, table):
        self._t = table

    def get(self, vendor_id):
        item = self._t.get_item(Key={"vendor_id": vendor_id}).get("Item")
        return Vendor(**item) if item else None

    def all(self):
        return [Vendor(**i) for i in self._t.scan().get("Items", [])]

    def update_bank(self, vendor_id, account, bank):
        self._t.update_item(
            Key={"vendor_id": vendor_id},
            UpdateExpression="SET bank_account = :a, bank_name = :b",
            ExpressionAttributeValues={":a": account, ":b": bank or ""},
        )


def resolve_vendor(registry: Registry, req: ChangeRequest) -> Optional[Vendor]:
    """Match the request to a registered vendor by sender domain, then by name in the text.

    A match here only selects WHICH registered record to protect; it never supplies contacts.
    """
    text = f"{req.subject}\n{req.body}".lower()
    for v in registry.all():
        if req.sender_domain and req.sender_domain in [d.lower() for d in v.domains]:
            return v
    for v in registry.all():
        if v.name.lower() in text:
            return v
    return None
