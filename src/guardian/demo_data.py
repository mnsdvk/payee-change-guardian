"""Synthetic vendors and scenario emails. All names/domains are fictional (.example)."""
from .models import Vendor

GOOD_IBAN = "GB82WEST12345698765432"
FRAUD_IBAN = "DE89370400440532013000"
LEGIT_IBAN = "NL91ABNA0417164300"
BASELINE = {"v-northwind": (GOOD_IBAN, "Westbridge Bank"), "v-harbor": ("FR1420041010050500013M02606", "Banque Harbor")}

def vendors(whatsapp: str = "+15550100001", sms: str = "+15550100001",
            approver: str = "ap-approver@example.com",
            supplier_email: str = "supplier-contact@example.com") -> list[Vendor]:
    return [
        Vendor("v-northwind", "Northwind Supply", ["northwind-supply.example"], whatsapp, sms,
               approver, GOOD_IBAN, "Westbridge Bank", 5000.0, supplier_email),
        Vendor("v-harbor", "Harbor Logistics", ["harbor-logistics.example"], whatsapp, None,
               approver, "FR1420041010050500013M02606", "Banque Harbor", 12000.0, supplier_email),
    ]

SCENARIOS = {
    "fraud": {
        "title": "Attack: bank change + new 'verification' phone number",
        "email": (
            "From: Accounts <billing@northwlnd-supply.example>\n"
            "Subject: URGENT: Northwind Supply new bank details\n\n"
            f"Northwind Supply has changed banks. Pay today's invoice USD 48,000 to IBAN {FRAUD_IBAN}. "
            "Bank: Fastcash Bank. Our old line is down, do not call it, confirm on +91 98765 43210 "
            "immediately. This is confidential."),
        "auth": {"spf": "FAIL", "dkim": "FAIL"},
    },
    "legit": {
        "title": "Legitimate: real supplier moves banks",
        "email": (
            "From: AR Team <ar@northwind-supply.example>\n"
            "Subject: Updated remittance details\n\n"
            f"Northwind Supply is moving banks next month. New IBAN {LEGIT_IBAN}. "
            "Bank: Harbor Bank. Next invoice USD 4,800."),
        "auth": {"spf": "PASS", "dkim": "PASS", "dmarc": "PASS"},
    },
}


def reset_demo(registry) -> None:
    """Return the demo vendors to their starting bank details so scenarios can be repeated."""
    for vid, (acct, bank) in BASELINE.items():
        if registry.get(vid):
            registry.update_bank(vid, acct, bank)
