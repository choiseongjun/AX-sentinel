"""Validate AX Sentinel against real AWS Bedrock, Knowledge Bases, and Cognito."""

import argparse
import json
import os
import urllib.request

import boto3
from botocore.exceptions import ClientError

from services.ai_analysis.app.engine import BedrockAnalysisEngine
from shared.auth import CognitoTokenVerifier
from shared.rag import BedrockKnowledgeBaseRetriever


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--invoke",
        action="store_true",
        help="Invoke Bedrock Converse and Knowledge Base retrieval (may incur AWS cost)",
    )
    args = parser.parse_args()
    if os.getenv("AWS_ENDPOINT_URL"):
        raise RuntimeError("AWS_ENDPOINT_URL must be unset for a real AWS integration check")

    region = os.getenv("AWS_REGION", "ap-northeast-2")
    pool_id = required("COGNITO_USER_POOL_ID")
    client_id = required("COGNITO_CLIENT_ID")
    model_id = required("BEDROCK_MODEL_ID")
    knowledge_base_id = required("BEDROCK_KNOWLEDGE_BASE_ID")
    data_source_id = required("BEDROCK_DATA_SOURCE_ID")

    identity = boto3.client("sts", region_name=region).get_caller_identity()
    cognito = boto3.client("cognito-idp", region_name=region)
    cognito.describe_user_pool(UserPoolId=pool_id)
    cognito.describe_user_pool_client(UserPoolId=pool_id, ClientId=client_id)

    issuer = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"
    with urllib.request.urlopen(
        f"{issuer}/.well-known/openid-configuration", timeout=10
    ) as response:
        discovery = json.load(response)
    with urllib.request.urlopen(discovery["jwks_uri"], timeout=10) as response:
        jwks = json.load(response)
    if not jwks.get("keys"):
        raise RuntimeError("Cognito JWKS did not contain signing keys")

    bedrock_agent = boto3.client("bedrock-agent", region_name=region)
    bedrock_agent.get_knowledge_base(knowledgeBaseId=knowledge_base_id)
    bedrock_agent.get_data_source(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
    )
    bedrock = boto3.client("bedrock", region_name=region)
    try:
        bedrock.get_inference_profile(inferenceProfileIdentifier=model_id)
    except ClientError:
        bedrock.get_foundation_model(modelIdentifier=model_id)

    login_verified = False
    username = os.getenv("COGNITO_TEST_USERNAME", "").strip()
    password = os.getenv("COGNITO_TEST_PASSWORD", "")
    if username and password:
        auth = cognito.admin_initiate_auth(
            UserPoolId=pool_id,
            ClientId=client_id,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
        access_token = auth["AuthenticationResult"]["AccessToken"]
        CognitoTokenVerifier(
            region=region,
            user_pool_id=pool_id,
            client_id=client_id,
        ).verify(access_token)
        login_verified = True

    bedrock_verified = False
    rag_verified = False
    if args.invoke:
        evidence = {
            "incident_id": "aws-integration-check",
            "equipment_id": "TEST-EQUIPMENT",
            "sensor_summary": "bearing temperature 110 C, threshold 90 C",
            "log_summary": "bearing overheat warning",
            "related_document_ids": [],
            "retrieved_context": [],
        }
        result = BedrockAnalysisEngine(region=region, model_id=model_id).analyze(evidence)
        bedrock_verified = bool(result.get("causes") and result.get("recommended_actions"))
        chunks = BedrockKnowledgeBaseRetriever(
            region=region,
            knowledge_base_id=knowledge_base_id,
        ).retrieve("bearing overheat maintenance procedure", 3)
        rag_verified = bool(chunks)

    print(
        json.dumps(
            {
                "account": identity["Account"],
                "region": region,
                "cognito_configuration": "verified",
                "cognito_login": "verified" if login_verified else "skipped_no_test_user",
                "bedrock_configuration": "verified",
                "bedrock_converse": "verified" if bedrock_verified else "skipped",
                "knowledge_base_retrieve": "verified" if rag_verified else "skipped",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
