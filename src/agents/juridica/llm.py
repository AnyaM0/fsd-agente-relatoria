from __future__ import annotations

from agents.shared_tools.llm_factory import build_shared_chat_model
from agents.shared_tools.segmentation_agent.lg_llm import SegmentationLLM


def build_juridica_chat_model(temperature: float = 0.0) -> SegmentationLLM:
    return build_shared_chat_model(
        temperature=temperature,
        databricks_base_url_keys=(
            "JURIDICA_DATABRICKS_BASE_URL",
            "COMPRAS_DATABRICKS_BASE_URL",
            "APPROVAL_MEMO_DATABRICKS_BASE_URL",
            "SEGMENTATION_DATABRICKS_BASE_URL",
        ),
        databricks_model_keys=(
            "JURIDICA_DATABRICKS_MODEL",
            "COMPRAS_DATABRICKS_MODEL",
            "APPROVAL_MEMO_DATABRICKS_MODEL",
            "SEGMENTATION_DATABRICKS_MODEL",
        ),
        azure_deployment_keys=(
            "JURIDICA_AZURE_DEPLOYMENT",
            "COMPRAS_AZURE_DEPLOYMENT",
            "APPROVAL_MEMO_AZURE_DEPLOYMENT",
            "SEGMENTATION_AZURE_DEPLOYMENT",
        ),
        openai_model_keys=(
            "JURIDICA_OPENAI_MODEL",
            "COMPRAS_OPENAI_MODEL",
            "APPROVAL_MEMO_OPENAI_MODEL",
            "SEGMENTATION_OPENAI_MODEL",
        ),
        default_databricks_model="databricks-claude-sonnet-4",
        default_openai_model="gpt-4.1-mini",
        error_context="juridica",
    )
