from dataclasses import dataclass
from typing import Dict, List, Optional
from app.config import settings
from app.ai.prompts import carrier_summary_v1, rate_outlook_v1, route_brief_v1


class PromptVersionNotFoundError(Exception):
    """Raised when a requested prompt feature or version is not found in the registry."""


@dataclass
class PromptTemplate:
    version: str
    system_prompt: str
    user_template: str


class PromptRegistry:
    def __init__(self):
        self._prompts: Dict[str, Dict[str, PromptTemplate]] = {}
        self.registry = self

    def register(self, feature: str, version: str, template: PromptTemplate) -> None:
        if feature not in self._prompts:
            self._prompts[feature] = {}
        self._prompts[feature][version] = template

    def list_versions(self, feature: str) -> List[str]:
        return list(self._prompts.get(feature, {}).keys())

    def get_prompt(self, feature: str, version: Optional[str] = None) -> PromptTemplate:
        if feature not in self._prompts:
            raise PromptVersionNotFoundError(f"No prompts registered for feature '{feature}'")

        if version is None:
            # Check configured settings default
            setting_name = f"AI_{feature.upper()}_PROMPT_VERSION"
            version = getattr(settings, setting_name, "v1")

        feature_prompts = self._prompts[feature]
        if version not in feature_prompts:
            raise PromptVersionNotFoundError(
                f"Prompt version '{version}' not found for feature '{feature}'. Available: {list(feature_prompts.keys())}"
            )
        return feature_prompts[version]


registry = PromptRegistry()

# Register default baseline v1 prompts
registry.register(
    "carrier_summarizer",
    "v1",
    PromptTemplate(
        version="v1",
        system_prompt=carrier_summary_v1.SYSTEM_PROMPT,
        user_template=carrier_summary_v1.USER_TEMPLATE,
    ),
)
registry.register(
    "rate_outlook",
    "v1",
    PromptTemplate(
        version="v1",
        system_prompt=rate_outlook_v1.SYSTEM_PROMPT,
        user_template=rate_outlook_v1.USER_TEMPLATE,
    ),
)
registry.register(
    "route_brief",
    "v1",
    PromptTemplate(
        version="v1",
        system_prompt=route_brief_v1.SYSTEM_PROMPT,
        user_template=route_brief_v1.USER_TEMPLATE,
    ),
)
