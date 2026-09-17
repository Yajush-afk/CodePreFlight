from __future__ import annotations

from collections.abc import Callable

from codepreflight_engine.models import ProviderDescriptor, ProviderKind, ProviderState


class FakeProviderAdapter:
    """Deterministic provider adapter used by process and orchestration tests."""

    descriptor = ProviderDescriptor(
        id="fake",
        name="Deterministic fake provider",
        kind=ProviderKind.LOCAL,
        state=ProviderState.READY,
        sends_code_remotely=False,
        detail="enabled explicitly for deterministic testing",
    )

    def __init__(self, response: str | Callable[[str, dict[str, object]], str]) -> None:
        self.response = response
        self.requests: list[tuple[str, dict[str, object]]] = []

    def review(self, prompt: str, schema: dict[str, object]) -> str:
        self.requests.append((prompt, schema))
        return self.response(prompt, schema) if callable(self.response) else self.response
