from __future__ import annotations

import json
import re
from typing import Any

from app.config import Settings


class BedrockService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any = None

    async def generate_json(self, model_id: str | None, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        text = await self.generate_text(model_id, system_prompt, json.dumps(payload, default=str))
        stripped = self._strip_fence(text)
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Bedrock returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Bedrock JSON response must be an object.")
        return parsed

    async def generate_text(self, model_id: str | None, system_prompt: str, user_text: str) -> str:
        if not model_id:
            raise RuntimeError("Bedrock model id is not configured.")
        client = self._get_client()
        response = client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={"temperature": 0, "maxTokens": 2048},
        )
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        text = "".join(block.get("text", "") for block in blocks).strip()
        if not text:
            raise RuntimeError("Bedrock response did not include text content.")
        return text

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 package is required for Bedrock Runtime.") from exc
        self._client = boto3.client("bedrock-runtime", region_name=self.settings.aws_region)
        return self._client

    @staticmethod
    def _strip_fence(text: str) -> str:
        match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text.strip(), flags=re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else text.strip()
