"""Prompt Versioning System (AI-A deliverable).

Dynamically loads versioned prompt templates from ai/prompts/ using importlib.
Prompt files follow the naming convention: {feature}_{version}.py
(e.g., route_brief_v1.py) and must define SYSTEM_PROMPT and USER_TEMPLATE.

This module is the single entry point for all prompt access — never import
prompt files directly elsewhere in the codebase.
"""
import importlib

from ai.logging import get_logger

logger = get_logger(__name__)

# Required attributes every prompt module must expose
_REQUIRED_ATTRS = ("SYSTEM_PROMPT", "USER_TEMPLATE")


def get_prompt_version(feature: str, version: str = "v1") -> dict[str, str]:
    """Dynamically load a versioned prompt module and return its templates.

    Args:
        feature: Prompt feature name (e.g., "route_brief", "carrier_summary").
        version: Prompt version string (e.g., "v1", "v2").

    Returns:
        Dict with keys "system_prompt" and "user_template".

    Raises:
        ModuleNotFoundError: If the prompt file does not exist.
        AttributeError: If the prompt file is missing required attributes.
    """
    module_name = f"ai.prompts.{feature}_{version}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        logger.error("prompt_module_not_found", module=module_name, error=str(exc))
        raise

    missing = [attr for attr in _REQUIRED_ATTRS if not hasattr(module, attr)]
    if missing:
        logger.error("prompt_missing_attributes", module=module_name, missing=missing)
        raise AttributeError(f"Prompt module {module_name} is missing: {missing}")

    logger.info("prompt_loaded", module=module_name, feature=feature, version=version)
    return {
        "system_prompt": module.SYSTEM_PROMPT,
        "user_template": module.USER_TEMPLATE,
    }


if __name__ == "__main__":
    # Smoke test: verify the prompt manager can load route_brief_v1
    try:
        prompts = get_prompt_version("route_brief", "v1")
        logger.info(
            "prompt_manager_smoke_test_ok",
            system_prompt_preview=prompts["system_prompt"][:100] + "...",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("prompt_manager_smoke_test_failed", error=str(exc))