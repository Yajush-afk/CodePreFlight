from pathlib import Path

from conftest import git

from codepreflight_engine.automation import AutomationManager


def test_review_mode_is_personal_repository_state(git_repository: Path) -> None:
    manager = AutomationManager(git_repository)

    preview = manager.configure("auto_plus", write=False)
    assert preview["mode"] == "auto_plus"
    assert not (git_repository / ".git" / "codepreflight" / "automation.json").exists()

    manager.configure("auto_plus", write=True)
    status = manager.status()

    assert status["mode"] == "auto_plus"
    assert ".git/codepreflight" in status["statePath"]


def test_automation_grant_is_scoped_and_revocable(git_repository: Path) -> None:
    manager = AutomationManager(git_repository)
    scope = {
        "provider": "fake",
        "kind": "local",
        "destination": "local",
        "executable": "/bin/fake",
        "executableVersion": "1.0",
        "model": "test",
        "repositoryIdentity": "repo-1",
        "configurationDigest": "config-1",
        "rulesDigest": "rules-1",
    }

    manager.grant(scope, write=True)
    assert manager.grant_status(scope)["valid"] is True

    changed = {**scope, "model": "different"}
    assert manager.grant_status(changed)["valid"] is False
    assert "model" in manager.grant_status(changed)["changed"]

    manager.revoke_grant(write=True)
    assert manager.grant_status(scope)["granted"] is False


def test_duplicate_commit_jobs_coalesce_and_interrupted_jobs_recover(
    git_repository: Path,
) -> None:
    manager = AutomationManager(git_repository)
    revision = git(git_repository, "rev-parse", "HEAD").strip()

    first = manager.enqueue("commit", revision, {"provider": "fake"})
    second = manager.enqueue("commit", revision, {"provider": "fake"})

    assert first["id"] == second["id"]
    assert second["coalesced"] is True

    manager.update_job(first["id"], "running")
    status = AutomationManager(git_repository).status(stale_after_seconds=0)
    recovered = next(job for job in status["jobs"] if job["id"] == first["id"])
    assert recovered["status"] == "interrupted"


def test_auto_plus_event_queues_each_commit_once(git_repository: Path) -> None:
    manager = AutomationManager(git_repository)
    manager.configure("auto_plus", write=True)
    revision = git(git_repository, "rev-parse", "HEAD").strip()

    first = manager.event("post-commit")
    second = manager.event("post-commit")

    assert first["job"]["revision"] == revision
    assert second["job"]["coalesced"] is True


def test_manual_mode_never_enqueues_provider_work(git_repository: Path) -> None:
    result = AutomationManager(git_repository).event("post-commit")

    assert result == {"mode": "manual", "action": "none"}
