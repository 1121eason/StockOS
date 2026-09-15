"""Replaceable structured-only providers; no implicit model selection or fake live fallback."""

import json
from abc import ABC, abstractmethod
from copy import deepcopy
from pathlib import Path

import httpx

from valuation_engine.db.store import digest


class ProviderUnavailable(RuntimeError):
    pass


class AIProvider(ABC):
    provider_name: str
    model_name: str
    model_version: str
    settings: dict

    @abstractmethod
    def request(self, stage, exact_prompt) -> dict:
        """Return {structured_output, response_model, raw_response}; no database access."""

    def analyze_document(self, exact_prompt):
        return self.extract_evidence(exact_prompt)

    def extract_evidence(self, exact_prompt):
        return self.request("extract", exact_prompt)

    def synthesize_features(self, exact_prompt):
        return self.request("synthesize", exact_prompt)

    def generate_challenge(self, exact_prompt):
        return self.request("challenge", exact_prompt)


def strict_schema(schema):
    value = deepcopy(schema)

    def visit(x):
        if isinstance(x, dict):
            if x.get("type") == "object":
                x["additionalProperties"] = False
                x["required"] = list(x.get("properties", {}))
            for v in x.values():
                visit(v)
        elif isinstance(x, list):
            for v in x:
                visit(v)

    visit(value)
    return value


class OpenAIProvider(AIProvider):
    provider_name = "openai"

    def __init__(self, api_key, model, model_version, reasoning=None, temperature=None):
        if not api_key or not model or not model_version:
            raise ProviderUnavailable(
                "Set OPENAI_API_KEY, QVE_AI_MODEL and QVE_AI_MODEL_VERSION locally"
            )
        self._api_key = api_key
        self.model_name, self.model_version = model, model_version
        self.settings = {
            "reasoning": reasoning,
            "temperature": temperature,
            "store": False,
            "tools": [],
            "max_output_tokens": 12000,
        }

    def request(self, stage, exact_prompt):
        body = {
            "model": self.model_name,
            "input": [
                {"role": "system", "content": exact_prompt["system"]},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": exact_prompt["task"],
                            "untrusted_data": exact_prompt["untrusted_data"],
                        },
                        sort_keys=True,
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": stage,
                    "strict": True,
                    "schema": strict_schema(exact_prompt["response_schema"]),
                }
            },
            "store": False,
            "tools": [],
            "max_output_tokens": 12000,
        }
        if self.settings["reasoning"] is not None:
            body["reasoning"] = {"effort": self.settings["reasoning"]}
        if self.settings["temperature"] is not None:
            body["temperature"] = self.settings["temperature"]
        with httpx.Client(timeout=180, follow_redirects=False) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                json=body,
                headers={"Authorization": "Bearer " + self._api_key},
            )
            response.raise_for_status()
            raw = response.json()
        if raw.get("status") != "completed":
            return {
                "structured_output": None,
                "response_model": raw.get("model"),
                "raw_response": raw,
            }
        texts = [
            c["text"]
            for o in raw.get("output", [])
            if o.get("type") == "message"
            for c in o.get("content", [])
            if c.get("type") == "output_text"
        ]
        try:
            output = json.loads("".join(texts))
        except ValueError:
            output = None
        return {
            "structured_output": output,
            "response_model": raw.get("model"),
            "raw_response": raw,
        }


class RecordedProvider(AIProvider):
    """Replay actual captured calls, strictly matched to prompt hash and original identity."""

    def __init__(self, path: Path):
        data = json.loads(path.read_text())
        self.provider_name = data["provider"]
        self.model_name = data["model_name"]
        self.model_version = data["model_version"]
        self.settings = data["settings"]
        self.calls = data["calls"]

    def request(self, stage, exact_prompt):
        key = digest([stage, exact_prompt])
        if key not in self.calls:
            raise ProviderUnavailable("No exact recorded response for this prompt")
        return self.calls[key]
