from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .git import GitRunner
from .models import BlastRadiusItem

MAX_TEXT_FILE_BYTES = 200_000
MAX_RESULTS = 50


@dataclass(frozen=True)
class ChangeSignals:
    path: str
    symbols: tuple[str, ...]
    routes: tuple[str, ...]
    config_keys: tuple[str, ...]


class BlastRadiusAnalyzer:
    def analyze(self, root: Path, changed_files: list[str]) -> list[BlastRadiusItem]:
        changed_signals = [self._change_signals(root, path) for path in changed_files]
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
            for changed in changed_signals:
                signal = self._relationship(candidate_path, content, changed)
                if signal and not self._already_reported(
                    signals, candidate_path, signal.relationship
                ):
                    signals.append(signal)
                    if len(signals) >= MAX_RESULTS:
                        return signals
        return signals

    def _relationship(
        self, candidate_path: str, content: str, changed: ChangeSignals
    ) -> BlastRadiusItem | None:
        changed_path = changed.path
        path = Path(changed_path)
        stem = path.stem
        module = path.with_suffix("").as_posix().replace("/", ".")
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
        for symbol in changed.symbols:
            if re.search(rf"\b{re.escape(symbol)}\s*\(", content):
                return BlastRadiusItem(
                    path=candidate_path,
                    relationship=(
                        "test reference" if self._is_test(candidate_path) else "call site"
                    ),
                    evidence=f"calls {symbol} defined in {changed_path}",
                    confidence="confirmed",
                )
            if re.search(rf"\b{re.escape(symbol)}\b", content):
                return BlastRadiusItem(
                    path=candidate_path,
                    relationship=(
                        "test reference" if self._is_test(candidate_path) else "symbol reference"
                    ),
                    evidence=f"references {symbol} defined in {changed_path}",
                    confidence="confirmed",
                )
        for route in changed.routes:
            if route in content:
                return BlastRadiusItem(
                    path=candidate_path,
                    relationship="route reference",
                    evidence=f"uses route {route} declared in {changed_path}",
                    confidence="confirmed",
                )
        for key in changed.config_keys:
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])", content):
                return BlastRadiusItem(
                    path=candidate_path,
                    relationship="configuration reference",
                    evidence=f"references configuration key {key} from {changed_path}",
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

    def _change_signals(self, root: Path, changed_path: str) -> ChangeSignals:
        candidate = root / changed_path
        try:
            content = (
                candidate.read_text(encoding="utf-8")
                if candidate.is_file() and candidate.stat().st_size <= MAX_TEXT_FILE_BYTES
                else ""
            )
        except (OSError, UnicodeDecodeError):
            content = ""
        supported_source = candidate.suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx"}
        symbols: set[str] = set()
        if supported_source:
            symbols.update(
                re.findall(
                    r"(?m)^\s*(?:export\s+)?(?:async\s+)?"
                    r"(?:def|class|function|interface|type)\s+"
                    r"([A-Za-z_][A-Za-z0-9_]*)",
                    content,
                )
            )
            symbols.update(
                re.findall(
                    r"(?m)^\s*export\s+(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)",
                    content,
                )
            )
        routes = (
            set(
                re.findall(
                    r"(?:route|path)\s*[=:]\s*['\"]([^'\"]+)['\"]|"
                    r"\.(?:get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]",
                    content,
                    re.IGNORECASE,
                )
            )
            if supported_source
            else set()
        )
        flattened_routes = {value for pair in routes for value in pair if value}
        config_keys: set[str] = set()
        if self._is_config(changed_path):
            config_keys.update(
                re.findall(r"(?m)^\s*[\"']?([A-Za-z_][A-Za-z0-9_.-]*)[\"']?\s*[:=]", content)
            )
        return ChangeSignals(
            path=changed_path,
            symbols=tuple(sorted(symbols)),
            routes=tuple(sorted(flattened_routes)),
            config_keys=tuple(sorted(config_keys)),
        )

    def _is_test(self, path: str) -> bool:
        lowered = path.lower()
        return "test" in lowered or "spec" in lowered

    def _is_config(self, path: str) -> bool:
        return Path(path).suffix.lower() in {".json", ".toml", ".yaml", ".yml", ".ini"}

    def _already_reported(
        self, signals: list[BlastRadiusItem], path: str, relationship: str
    ) -> bool:
        return any(item.path == path and item.relationship == relationship for item in signals)
