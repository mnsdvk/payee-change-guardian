import os
from functools import lru_cache

from ..channels.messenger import Messenger
from ..engine import Guardian
from .. import ai
from ..registry import DynamoRegistry
from ..store import DynamoCaseStore


@lru_cache(maxsize=1)
def guardian() -> Guardian:
    import boto3
    ddb = boto3.resource("dynamodb")
    model, analyst = ai.from_env(lambda: boto3.client("bedrock-runtime"))
    return Guardian(DynamoRegistry(ddb.Table(os.environ["VENDORS_TABLE"])),
                    DynamoCaseStore(ddb.Table(os.environ["CASES_TABLE"])),
                    Messenger(), model=model, analyst=analyst)


def sfn():
    import boto3
    return boto3.client("stepfunctions")
