from __future__ import annotations

from collections import Counter
from pathlib import Path

from .git import GitRunner
from .models import (
    ChangeKind,
    FileChange,
    ProjectContext,
    Remote,
    RepositorySnapshot,
)

STATUS_KINDS = {
    "A": ChangeKind.ADDED,
    "M": ChangeKind.MODIFIED,
    "D": ChangeKind.DELETED,
    "R": ChangeKind.RENAMED,
    "C": ChangeKind.COPIED,
    "U": ChangeKind.UNMERGED,
    "T": ChangeKind.TYPE_CHANGED,
}

LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".pyi": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
}

MANIFESTS = {
    "package.json": ("Node.js",),
    "pyproject.toml": ("Python",),
    "requirements.txt": ("Python",),
    "go.mod": ("Go",),
    "Cargo.toml": ("Rust",),
    "pom.xml": ("Java",),
    "build.gradle": ("Java",),
}

ATTENTION_PATTERNS = {
    "authentication": ("auth", "session", "token", "permission"),
    "database migration": ("migration", "migrations", "schema"),
    "deployment": ("docker", "deploy", "terraform", ".github/workflows"),
    "public interface": ("api", "routes", "controller", "public"),
    "secrets or environment": (".env", "secret", "credential"),
    "tests": ("test", "spec"),
}


class RepositoryInspector:
    def inspect(self, path: Path) -> RepositorySnapshot:
        initial = GitRunner(path)
        root = initial.root()
        git = GitRunner(root)
        branch_result = git.run("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        branch = branch_result.stdout.strip() or None
        detached = None if branch else self._optional(git, "rev-parse", "--short", "HEAD")
        upstream = self._optional(git, "rev-parse", "--abbrev-ref", "@{upstream}")
        ahead, behind = self._ahead_behind(git, upstream)
        files = self._changes(git)
        conflicts = sorted(
            path
            for path in git.run(
                "diff", "--name-only", "--diff-filter=U", check=False
            ).stdout.splitlines()
            if path
        )

        return RepositorySnapshot(
            root=str(root),
            branch=branch,
            detached_head=detached,
            base_branch=self._base_branch(git, branch),
            upstream=upstream,
            ahead=ahead,
            behind=behind,
            remotes=self._remotes(git),
            files=files,
            conflicts=conflicts,
            project=self._project_context(root, files),
        )

    def _optional(self, git: GitRunner, *args: str) -> str | None:
        result = git.run(*args, check=False)
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None

    def _ahead_behind(self, git: GitRunner, upstream: str | None) -> tuple[int, int]:
        if not upstream:
            return 0, 0
        result = git.run("rev-list", "--left-right", "--count", f"HEAD...{upstream}", check=False)
        if result.returncode != 0:
            return 0, 0
        values = result.stdout.split()
        return (int(values[0]), int(values[1])) if len(values) == 2 else (0, 0)

    def _base_branch(self, git: GitRunner, branch: str | None) -> str | None:
        remote_head = self._optional(git, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        if remote_head:
            return remote_head.removeprefix("origin/")
        for candidate in ("main", "master"):
            if (
                candidate != branch
                and git.run(
                    "show-ref", "--verify", f"refs/heads/{candidate}", check=False
                ).returncode
                == 0
            ):
                return candidate
        return None

    def _changes(self, git: GitRunner) -> list[FileChange]:
        changes: dict[str, FileChange] = {}
        self._merge_name_status(
            changes, git.run("diff", "--cached", "--name-status", "-z").stdout, staged=True
        )
        self._merge_name_status(
            changes, git.run("diff", "--name-status", "-z").stdout, staged=False
        )
        untracked = git.run("ls-files", "--others", "--exclude-standard", "-z").stdout
        for path in filter(None, untracked.split("\0")):
            changes[path] = FileChange(path=path, kind=ChangeKind.UNTRACKED, untracked=True)
        return sorted(changes.values(), key=lambda item: item.path)

    def _merge_name_status(
        self, changes: dict[str, FileChange], output: str, *, staged: bool
    ) -> None:
        parts = output.split("\0")
        index = 0
        while index < len(parts) and parts[index]:
            status = parts[index]
            path = parts[index + 1]
            index += 2
            previous_path = None
            if status[0] in {"R", "C"} and index < len(parts):
                previous_path, path = path, parts[index]
                index += 1
            existing = changes.get(path)
            kind = STATUS_KINDS.get(status[0], ChangeKind.UNKNOWN)
            if existing:
                changes[path] = existing.model_copy(
                    update={
                        "staged": existing.staged or staged,
                        "unstaged": existing.unstaged or not staged,
                    }
                )
            else:
                changes[path] = FileChange(
                    path=path,
                    kind=kind,
                    staged=staged,
                    unstaged=not staged,
                    previous_path=previous_path,
                )

    def _remotes(self, git: GitRunner) -> list[Remote]:
        values: dict[str, dict[str, str]] = {}
        for line in git.run("remote", "-v", check=False).stdout.splitlines():
            fields = line.split()
            if len(fields) < 3:
                continue
            name, url, operation = fields[0], fields[1], fields[2]
            values.setdefault(name, {})["fetch_url" if "fetch" in operation else "push_url"] = url
        return [Remote(name=name, **urls) for name, urls in sorted(values.items())]

    def _project_context(self, root: Path, files: list[FileChange]) -> ProjectContext:
        tracked = GitRunner(root).run("ls-files", "-z", check=False).stdout.split("\0")
        paths = [path for path in tracked if path]
        languages = Counter(
            language
            for path in paths
            if (language := LANGUAGE_EXTENSIONS.get(Path(path).suffix.lower()))
        )
        manifests = sorted(path for path in paths if Path(path).name in MANIFESTS)
        names = {Path(path).name for path in paths}
        test_tools = [
            tool
            for marker, tool in (
                ("pytest.ini", "pytest"),
                ("vitest.config.ts", "vitest"),
                ("jest.config.js", "jest"),
            )
            if marker in names
        ]
        if "pyproject.toml" in names:
            test_tools.append("pytest (possible)")
        if "package.json" in names:
            test_tools.append("package scripts")
        lint_tools = [
            tool
            for marker, tool in (
                ("ruff.toml", "ruff"),
                ("eslint.config.js", "eslint"),
                (".eslintrc", "eslint"),
            )
            if marker in names
        ]
        build_tools = [
            tool
            for marker, tool in (
                ("package.json", "Node.js scripts"),
                ("pyproject.toml", "Python build"),
                ("Makefile", "make"),
            )
            if marker in names
        ]
        changed_paths = [item.path.lower() for item in files]
        attention = sorted(
            area
            for area, patterns in ATTENTION_PATTERNS.items()
            if any(pattern in path for pattern in patterns for path in changed_paths)
        )
        return ProjectContext(
            languages=[name for name, _ in languages.most_common()],
            manifests=manifests,
            test_tools=sorted(set(test_tools)),
            lint_tools=sorted(set(lint_tools)),
            build_tools=sorted(set(build_tools)),
            attention_areas=attention,
        )
