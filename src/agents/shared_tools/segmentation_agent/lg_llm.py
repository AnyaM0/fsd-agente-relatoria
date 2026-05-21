from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from openai import OpenAI
from pydantic import BaseModel

from agents.shared_tools.llm_factory import build_shared_chat_model


_JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _schema_prompt(schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=True, indent=2)
    return (
        "Return only valid JSON that matches this schema exactly.\n"
        "Do not add markdown, explanations, or extra keys.\n"
        f"{schema_json}"
    )


def _extract_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    block_match = _JSON_BLOCK_RE.search(stripped)
    if block_match:
        return json.loads(block_match.group(1).strip())

    if stripped.startswith("{") and stripped.endswith("}"):
        return json.loads(stripped)

    balanced_object = _extract_balanced_json_object(stripped)
    if balanced_object is not None:
        return json.loads(balanced_object)

    raise ValueError(f"Model did not return a JSON object: {stripped[:300]}")


def _extract_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _message_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(text)
            else:
                text = getattr(item, "text", None)
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _invoke_databricks_structured(
    client: OpenAI,
    *,
    model_name: str,
    prompt: str,
    schema: type[BaseModel],
    system_prompt: str | None,
    temperature: float,
) -> BaseModel:
    messages = []
    combined_system_prompt = _schema_prompt(schema)
    if system_prompt:
        combined_system_prompt = f"{system_prompt}\n\n{combined_system_prompt}"
    messages.append({"role": "system", "content": combined_system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
    )
    content = _message_content_to_text(response.choices[0].message.content)
    try:
        return schema.model_validate(_extract_json_payload(content))
    except Exception:
        repaired = _repair_databricks_json(
            client,
            model_name=model_name,
            raw_content=content,
            schema=schema,
            temperature=temperature,
        )
        return schema.model_validate(_extract_json_payload(repaired))


def _invoke_databricks_text(
    client: OpenAI,
    *,
    model_name: str,
    prompt: str,
    system_prompt: str | None,
    temperature: float,
) -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
    )
    return _message_content_to_text(response.choices[0].message.content).strip()


def _repair_databricks_json(
    client: OpenAI,
    *,
    model_name: str,
    raw_content: str,
    schema: type[BaseModel],
    temperature: float,
) -> str:
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": (
                    "You repair malformed JSON. "
                    "Return only valid JSON that matches the required schema exactly. "
                    "Do not add markdown or commentary.\n\n"
                    f"{_schema_prompt(schema)}"
                ),
            },
            {
                "role": "user",
                "content": (
                    "Repair this malformed JSON output so it becomes valid JSON matching the schema.\n\n"
                    f"{raw_content}"
                ),
            },
        ],
        temperature=temperature,
    )
    return _message_content_to_text(response.choices[0].message.content).strip()


@dataclass
class SegmentationLLM:
    provider: Literal["databricks", "langchain"]
    client: Any
    model_name: str | None = None
    temperature: float = 0.0

    def invoke_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system_prompt: str | None = None,
    ) -> BaseModel:
        if self.provider == "databricks":
            return _invoke_databricks_structured(
                self.client,
                model_name=self.model_name or "",
                prompt=prompt,
                schema=schema,
                system_prompt=system_prompt,
                temperature=self.temperature,
            )

        structured_model = self.client.with_structured_output(schema)
        messages = [HumanMessage(content=prompt)]
        if system_prompt:
            messages.insert(0, SystemMessage(content=system_prompt))
        return structured_model.invoke(messages)

    def invoke_text(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str:
        if self.provider == "databricks":
            return _invoke_databricks_text(
                self.client,
                model_name=self.model_name or "",
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=self.temperature,
            )

        messages = [HumanMessage(content=prompt)]
        if system_prompt:
            messages.insert(0, SystemMessage(content=system_prompt))
        response = self.client.invoke(messages)
        return _message_content_to_text(getattr(response, "content", response)).strip()


def build_default_chat_model(temperature: float = 0.0):
    return build_shared_chat_model(
        temperature=temperature,
        databricks_base_url_keys=("SEGMENTATION_DATABRICKS_BASE_URL",),
        databricks_model_keys=("SEGMENTATION_DATABRICKS_MODEL",),
        azure_deployment_keys=("SEGMENTATION_AZURE_DEPLOYMENT",),
        openai_model_keys=("SEGMENTATION_OPENAI_MODEL",),
        default_databricks_model="databricks-claude-sonnet-4",
        default_openai_model="gpt-4.1-mini",
        error_context="segmentation agent",
    )
