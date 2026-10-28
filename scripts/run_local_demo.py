#!/usr/bin/env python3
"""Offline end-to-end run of both demo scenarios. Uses fake AWS clients, so it needs no credentials.

    python scripts/run_local_demo.py
"""
import json
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root / "tests"))

from fakes import FakeSes, FakeSms, FakeSocial  # noqa: E402
from guardian.channels.messenger import Messenger  # noqa: E402
from guardian.demo_data import SCENARIOS, vendors  # noqa: E402
from guardian.engine import Guardian, LocalRunner  # noqa: E402
from guardian.registry import InMemoryRegistry  # noqa: E402
from guardian.store import InMemoryCaseStore  # noqa: E402


def run(name, replies):
    reg = InMemoryRegistry(vendors())
    social, sms, ses = FakeSocial(), FakeSms(), FakeSes()
    m = Messenger(social, sms, ses, whatsapp_origination_id="phone-number-id-demo",
                  sms_origination="+15550000000", from_address="guardian@example.com")
    sc = SCENARIOS[name]
    case = LocalRunner(Guardian(reg, InMemoryCaseStore(), m)).run(sc["email"], replies, sc.get("auth"))
    print(f"\n=== {sc['title']} ===")
    r = case.get("risk", {})
    print(f"risk: {r.get('level')} ({r.get('score')})")
    for s in r.get("signals", []):
        print(f"  - {s['code']}: {s['detail']}")
    for t in case["timeline"]:
        print(f"  [{t['type']}] {t['detail']}")
    print(f"state: {case['state']}\noutcome: {case.get('outcome')}")
    print("WhatsApp sent to:", [json.loads(c['message'])['to'] for c in social.calls])
    print("Registered account now:", reg.get("v-northwind").bank_account)


run("fraud", {"whatsapp": {"button": "GUARDIAN_DENIED"}})
run("legit", {"whatsapp": {"button": "GUARDIAN_AUTHORIZED"}})
