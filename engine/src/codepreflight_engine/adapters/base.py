from __future__ import annotations

from typing import Protocol

from codepreflight_engine.models import ProviderDescriptor


class ProviderAdapter(Protocol):
    descriptor: ProviderDescriptor

    def review(self, prompt: str, schema: dict[str, object]) -> str: ...
