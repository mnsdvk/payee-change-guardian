#!/usr/bin/env python3
"""Read-only check of which services this account and region can use. Sends no messages.

    python scripts/check_aws.py            # uses your configured region
    python scripts/check_aws.py ap-south-1 # or pass one
"""
import sys

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

region = sys.argv[1] if len(sys.argv) > 1 else boto3.Session().region_name or "us-east-1"
print(f"Region: {region}\n")


def check(name, fn):
    try:
        print(f"[ OK ] {name}: {fn()}")
    except EndpointConnectionError:
        print(f"[FAIL] {name}: service not available in this region")
    except ClientError as e:
        c = e.response["Error"]
        print(f"[FAIL] {name}: {c.get('Code')} - {c.get('Message', '')[:160]}")
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__}: {str(e)[:160]}")


def who():
    a = boto3.client("sts", region_name=region).get_caller_identity()["Account"]
    return f"signed in, account ending {a[-4:]}"


def social():
    r = boto3.client("socialmessaging", region_name=region).list_linked_whatsapp_business_accounts()
    return f"{len(r.get('linkedAccounts', []))} WhatsApp account(s) linked"


def sms():
    r = boto3.client("pinpoint-sms-voice-v2", region_name=region).describe_account_attributes()
    return "reachable"


def ses():
    r = boto3.client("sesv2", region_name=region).get_account()
    return f"sending enabled={r.get('SendingEnabled')}, production access={r.get('ProductionAccessEnabled')}"


def bedrock_model(model_id):
    def _f():
        b = boto3.client("bedrock-runtime", region_name=region)
        out = b.converse(modelId=model_id,
                         messages=[{"role": "user", "content": [{"text": "Reply with the word ok."}]}],
                         inferenceConfig={"maxTokens": 10})
        return "model replied: " + out["output"]["message"]["content"][0]["text"].strip()[:20]
    return _f


def comprehend():
    r = boto3.client("comprehend", region_name=region).detect_sentiment(Text="yes, that is fine", LanguageCode="en")
    return "sentiment " + r["Sentiment"]


def translate():
    r = boto3.client("translate", region_name=region).translate_text(Text="yes", SourceLanguageCode="en", TargetLanguageCode="hi")
    return "translated ok"


def ddb():
    return f"{len(boto3.client('dynamodb', region_name=region).list_tables()['TableNames'])} table(s)"


def lam():
    return f"{len(boto3.client('lambda', region_name=region).list_functions()['Functions'])} function(s)"


def sfn():
    return f"{len(boto3.client('stepfunctions', region_name=region).list_state_machines()['stateMachines'])} state machine(s)"


def cfn():
    boto3.client("cloudformation", region_name=region).list_stacks()
    return "reachable"


def s3():
    boto3.client("s3", region_name=region).list_buckets()
    return "reachable"


check("Sign-in", who)
check("End User Messaging Social (WhatsApp)", social)
check("End User Messaging SMS", sms)
check("SES v2", ses)
for mid in ("us.amazon.nova-micro-v1:0", "amazon.nova-micro-v1:0", "us.amazon.nova-lite-v1:0",
            "us.amazon.nova-2-lite-v1:0", "us.anthropic.claude-haiku-4-5-20251001-v1:0"):
    check(f"Bedrock {mid}", bedrock_model(mid))
check("Amazon Comprehend", comprehend)
check("Amazon Translate", translate)
check("DynamoDB", ddb)
check("Lambda", lam)
check("Step Functions", sfn)
check("CloudFormation", cfn)
check("S3", s3)