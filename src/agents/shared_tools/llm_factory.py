from __future__ import annotations

import os
from typing import TYPE_CHECKING

from langchain_openai import AzureChatOpenAI, ChatOpenAI
from openai import OpenAI

if TYPE_CHECKING:
    from agents.shared_tools.segmentation_agent.lg_llm import SegmentationLLM


def normalize_env_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
        normalized = normalized[1:-1].strip()
    return normalized


def get_first_env(*keys: str) -> str | None:
    for key in keys:
        value = normalize_env_value(os.getenv(key))
        if value:
            return value
    return None


def build_shared_chat_model(
    *,
    temperature: float = 0.0,
    databricks_base_url_keys: tuple[str, ...] = (),
    databricks_model_keys: tuple[str, ...] = (),
    azure_deployment_keys: tuple[str, ...] = (),
    openai_model_keys: tuple[str, ...] = (),
    default_databricks_model: str = "databricks-claude-sonnet-4",
    default_openai_model: str = "gpt-4.1-mini",
    error_context: str = "shared agent",
) -> SegmentationLLM:
    from agents.shared_tools.segmentation_agent.lg_llm import SegmentationLLM

    databricks_token = get_first_env("DATABRICKS_TOKEN")
    databricks_base_url = get_first_env(*databricks_base_url_keys, "DATABRICKS_BASE_URL")
    databricks_model = get_first_env(*databricks_model_keys, "DATABRICKS_CHAT_MODEL", "DATABRICKS_MODEL") or default_databricks_model

    if databricks_token and databricks_base_url:
        print("Using databricks LLM inference")
        return SegmentationLLM(
            provider="databricks",
            client=OpenAI(
                api_key=databricks_token,
                base_url=databricks_base_url.rstrip("/"),
            ),
            model_name=databricks_model,
            temperature=temperature,
        )

    azure_endpoint = get_first_env("AZURE_OPENAI_ENDPOINT")
    azure_api_key = get_first_env("AZURE_OPENAI_API_KEY")
    azure_api_version = get_first_env("AZURE_OPENAI_API_VERSION") or "2024-12-01-preview"
    azure_deployment = get_first_env(*azure_deployment_keys, "AZURE_OPENAI_DEPLOYMENT_GPT5_MINI", "AZURE_OPENAI_DEPLOYMENT")

    if azure_endpoint and azure_api_key and azure_deployment:
        return SegmentationLLM(
            provider="langchain",
            client=AzureChatOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=azure_api_key,
                api_version=azure_api_version,
                azure_deployment=azure_deployment,
                temperature=temperature,
            ),
            temperature=temperature,
        )

    openai_model = get_first_env(*openai_model_keys) or default_openai_model
    if get_first_env("OPENAI_API_KEY"):
        return SegmentationLLM(
            provider="langchain",
            client=ChatOpenAI(model=openai_model, temperature=temperature),
            temperature=temperature,
        )

    raise ValueError(
        f"No LLM configuration found for {error_context}. Set Databricks vars "
        "(DATABRICKS_TOKEN plus a base URL), or Azure OpenAI vars, or OPENAI_API_KEY."
    )
