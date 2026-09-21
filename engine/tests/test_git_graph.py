from pathlib import Path

from conftest import git

from codepreflight_engine.workspace import RepositoryWorkspace


def test_base_graph_is_one_lane(git_repository: Path) -> None:
    graph = RepositoryWorkspace().run(git_repository, {"action": "graph"})
    assert graph["lanes"] == [{"id": "base", "label": "main"}]
    assert graph["commits"][0]["subject"] == "Initial commit"
    assert graph["baseHead"] == graph["head"]
    assert graph["localOnly"] is True


def test_feature_graph_has_two_lanes_and_merge_base(git_repository: Path) -> None:
    merge_base = git(git_repository, "rev-parse", "HEAD").strip()
    git(git_repository, "switch", "-c", "feature")
    (git_repository / "feature.py").write_text("value = 1\n")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Feature")
    git(git_repository, "switch", "main")
    (git_repository / "base.py").write_text("base = True\n")
    git(git_repository, "add", "base.py")
    git(git_repository, "commit", "-m", "Base change")
    base_head = git(git_repository, "rev-parse", "HEAD").strip()
    git(git_repository, "switch", "feature")
    (git_repository / "feature.py").write_text("value = 2\n")
    graph = RepositoryWorkspace().run(git_repository, {"action": "graph"})
    assert [item["id"] for item in graph["lanes"]] == ["base", "current"]
    assert graph["mergeBase"] == merge_base
    assert graph["baseHead"] == base_head
    assert {item["lane"] for item in graph["commits"]} == {"base", "current", "shared"}
    assert graph["workingTree"]["unstaged"] == 1
    first = graph["fingerprint"]
    git(git_repository, "add", "feature.py")
    assert RepositoryWorkspace().run(git_repository, {"action": "graph"})["fingerprint"] != first


def test_missing_base_has_guidance(git_repository: Path) -> None:
    git(git_repository, "branch", "-m", "trunk")
    graph = RepositoryWorkspace().run(git_repository, {"action": "graph"})
    assert len(graph["lanes"]) == 1
    assert "Base not detected" in graph["note"]
