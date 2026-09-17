from __future__ import annotations

import re
from pathlib import Path

from .git import GitRunner
from .models import BlastRadiusItem

MAX_TEXT_FILE_BYTES = 200_000
MAX_RESULTS = 50


class BlastRadiusAnalyzer:
    def analyze(self, root: Path, changed_files: list[str]) -> list[BlastRadiusItem]:
        tracked = [
            path
            for path in GitRunner(root).run("ls-files", "-z").stdout.split("\0")
            if path and path not in changed_files
        ]
        signals: list[BlastRadiusItem] = []
        for candidate_path in tracked:
            candidate = root / candidate_path
            if not candidate.is_file() or candidate.stat().st_size > MAX_TEXT_FILE_BYTES:
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for changed_path in changed_files:
                signal = self._relationship(candidate_path, content, changed_path)
                if signal and not self._already_reported(
                    signals, candidate_path, signal.relationship
                ):
                    signals.append(signal)
                    if len(signals) >= MAX_RESULTS:
                        return signals
        return signals

    def _relationship(
        self, candidate_path: str, content: str, changed_path: str
    ) -> BlastRadiusItem | None:
        changed = Path(changed_path)
        stem = changed.stem
        module = changed.with_suffix("").as_posix().replace("/", ".")
        escaped_stem = re.escape(stem)
        escaped_module = re.escape(module)
        import_patterns = (
            rf"(?m)^\s*(?:from|import)\s+{escaped_module}(?:\s|\.|$)",
            rf"(?m)^\s*(?:import|export).*?from\s+['\"][^'\"]*{escaped_stem}['\"]",
            rf"(?:require|import)\(['\"][^'\"]*{escaped_stem}['\"]\)",
        )
        if any(re.search(pattern, content) for pattern in import_patterns):
            relationship = "test reference" if self._is_test(candidate_path) else "direct import"
            return BlastRadiusItem(
                path=candidate_path,
                relationship=relationship,
                evidence=f"references module from {changed_path}",
                confidence="confirmed",
            )
        if stem and re.search(rf"\b{escaped_stem}\b", content, re.IGNORECASE):
            relationship = (
                "configuration reference"
                if self._is_config(candidate_path)
                else "textual reference"
            )
            return BlastRadiusItem(
                path=candidate_path,
                relationship=relationship,
                evidence=f"mentions {stem} from {changed_path}",
                confidence="inferred",
            )
        return None

    def _is_test(self, path: str) -> bool:
        lowered = path.lower()
        return "test" in lowered or "spec" in lowered

    def _is_config(self, path: str) -> bool:
        return Path(path).suffix.lower() in {".json", ".toml", ".yaml", ".yml", ".ini"}

    def _already_reported(
        self, signals: list[BlastRadiusItem], path: str, relationship: str
    ) -> bool:
        return any(item.path == path and item.relationship == relationship for item in signals)
