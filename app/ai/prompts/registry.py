from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class PromptVersionNotFoundError(Exception):
    """Raised when a requested prompt version is not found in the registry."""
    pass


@dataclass
class PromptTemplate:
    version: str
    system_prompt: str
    user_template: str
    description: str = ""


class PromptRegistry:
    """Registry for managing and resolving versioned AI prompt templates."""

    def __init__(self) -> None:
        # Structure: {feature_name: {version: PromptTemplate}}
        self._prompts: Dict[str, Dict[str, PromptTemplate]] = {}

    def register(self, feature: str, version: str, template: PromptTemplate) -> None:
        """Register a prompt template for a given feature and version."""
        if feature not in self._prompts:
            self._prompts[feature] = {}
        self._prompts[feature][version] = template
        logger.debug("Registered prompt: feature=%s, version=%s", feature, version)

    def get_prompt(self, feature: str, version: Optional[str] = None) -> PromptTemplate:
        """Resolve a prompt template for a feature.

        If version is explicitly provided, look up that version.
        If version is None, resolve the active version configured in settings.
        Raises PromptVersionNotFoundError if the feature or version is not registered.
        """
        if feature not in self._prompts:
            raise PromptVersionNotFoundError(f"No prompts registered for feature '{feature}'")

        target_version = version
        if not target_version:
            target_version = self._get_configured_version(feature)

        feature_prompts = self._prompts[feature]
        if target_version not in feature_prompts:
            raise PromptVersionNotFoundError(
                f"Prompt version '{target_version}' not found for feature '{feature}'. "
                f"Available versions: {list(feature_prompts.keys())}"
            )

        return feature_prompts[target_version]

    def list_versions(self, feature: str) -> List[str]:
        """List all registered version strings for a given feature."""
        return list(self._prompts.get(feature, {}).keys())

    def _get_configured_version(self, feature: str) -> str:
        """Retrieve the configured active prompt version for a feature from settings."""
        if feature in ("carrier_summarizer", "carrier_advisory_summary"):
            return getattr(settings, "AI_CARRIER_SUMMARIZER_PROMPT_VERSION", "v1")
        elif feature in ("rate_outlook", "rate_outlook_narrator"):
            return getattr(settings, "AI_RATE_OUTLOOK_PROMPT_VERSION", "v1")
        elif feature in ("route_brief", "route_brief_generator"):
            return getattr(settings, "AI_ROUTE_BRIEF_PROMPT_VERSION", "v1")
        return "v1"


# Global singleton instance
registry = PromptRegistry()


def _init_default_prompts() -> None:
    """Pre-register baseline v1 prompts from existing prompt files."""
    from app.ai.prompts import carrier_summary_v1, rate_outlook_v1, route_brief_v1

    # Carrier Summarizer v1
    registry.register(
        "carrier_summarizer",
        "v1",
        PromptTemplate(
            version="v1",
            system_prompt=carrier_summary_v1.SYSTEM_PROMPT,
            user_template=carrier_summary_v1.USER_TEMPLATE,
            description="Carrier advisory summary baseline prompt v1",
        ),
    )

    # Rate Outlook v1
    registry.register(
        "rate_outlook",
        "v1",
        PromptTemplate(
            version="v1",
            system_prompt=rate_outlook_v1.SYSTEM_PROMPT,
            user_template=rate_outlook_v1.USER_TEMPLATE,
            description="Rate outlook narrator baseline prompt v1",
        ),
    )

    # Route Brief v1
    registry.register(
        "route_brief",
        "v1",
        PromptTemplate(
            version="v1",
            system_prompt=route_brief_v1.SYSTEM_PROMPT,
            user_template=route_brief_v1.USER_TEMPLATE,
            description="Route brief generator baseline prompt v1",
        ),
    )


# Register default v1 prompts upon module load
_init_default_prompts()


def get_prompt(feature: str, version: Optional[str] = None) -> PromptTemplate:
    """Helper function to get a prompt from the default global registry."""
    return registry.get_prompt(feature, version)
