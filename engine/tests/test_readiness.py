from pathlib import Path

from codepreflight_engine.models import ProviderDescriptor, ProviderKind
from codepreflight_engine.readiness import ProviderHealth, review_readiness


def descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        id="fake",
        name="Fake",
        kind=ProviderKind.LOCAL,
        sends_code_remotely=False,
        model_name="small",
    )


def test_risky_workflow_requires_real_invocation_evidence() -> None:
    provider = descriptor()
    assert review_readiness(provider)["state"] == "ready"
    readiness = review_readiness(provider, require_verified=True)
    assert readiness["state"] == "action_required"
    assert readiness["blockers"][0]["action"]["type"] == "test_provider"


def test_health_evidence_tracks_configuration_and_failure(git_repository: Path) -> None:
    provider = descriptor()
    health = ProviderHealth(git_repository)
    assert not health.verified(provider, {})
    health.record(provider, {})
    assert health.verified(provider, {})
    assert not health.verified(provider.model_copy(update={"variant_name": "high"}), {})
    assert not health.verified(provider, {"providers": {"fake": {"base_url": "other"}}})
    health.invalidate(provider)
    assert not health.verified(provider, {})


def test_degraded_provider_never_reports_ready() -> None:
    provider = descriptor().model_copy(update={"availability": "degraded"})
    assert review_readiness(provider)["state"] == "action_required"


def test_corrupt_evidence_is_not_verified(git_repository: Path) -> None:
    health = ProviderHealth(git_repository)
    health.path.parent.mkdir(parents=True, exist_ok=True)
    health.path.write_text('{"fake": null}')
    assert not health.verified(descriptor(), {})


def test_proxy_environment_is_preserved_without_unrelated_secrets(monkeypatch) -> None:
    from codepreflight_engine.adapters.process import sanitized_environment

    monkeypatch.setenv("HTTPS_PROXY", "https://proxy.invalid")
    monkeypatch.setenv("SSL_CERT_FILE", "/cert.pem")
    monkeypatch.setenv("UNRELATED_SECRET", "private")
    environment = sanitized_environment()
    assert environment["HTTPS_PROXY"] == "https://proxy.invalid"
    assert environment["SSL_CERT_FILE"] == "/cert.pem"
    assert "UNRELATED_SECRET" not in environment
