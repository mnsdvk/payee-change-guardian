"""SES inbound -> S3 -> this Lambda. Opens a case and starts the Step Functions verification."""
import json
import os



from .common import guardian, sfn

AUTH_KEYS = {"spfVerdict": "spf", "dkimVerdict": "dkim", "dmarcVerdict": "dmarc"}


def start_case(raw: bytes, auth: dict | None = None) -> dict:
    g = guardian()
    case = g.open_case(raw, auth)
    if case["state"] == "HELD":
        sfn().start_execution(
            stateMachineArn=os.environ["STATE_MACHINE_ARN"], name=case["case_id"],
            input=json.dumps({"case_id": case["case_id"],
                              "timeout_seconds": int(os.environ.get("VERIFY_TIMEOUT_SECONDS", "900"))}))
    return case


def handler(event, _ctx):
    import boto3
    s3 = boto3.client("s3")
    out = []
    for rec in event.get("Records", []):
        b, k = rec["s3"]["bucket"]["name"], rec["s3"]["object"]["key"]
        obj = s3.get_object(Bucket=b, Key=k)
        out.append(start_case(obj["Body"].read())["case_id"])
    return {"cases": out}
