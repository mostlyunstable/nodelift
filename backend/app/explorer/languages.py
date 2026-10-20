# ruff: noqa: E501
"""Language detection. Ids are Monaco language ids so the editor can use them directly."""

from pathlib import PurePosixPath

_BY_EXT = {
    ".py": "python", ".pyi": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript", ".json": "json", ".jsonc": "json",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss", ".less": "less",
    ".yml": "yaml", ".yaml": "yaml", ".sql": "sql", ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".md": "markdown", ".markdown": "markdown", ".xml": "xml", ".toml": "ini", ".ini": "ini",
    ".java": "java", ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".cs": "csharp", ".swift": "swift", ".kt": "kotlin",
    ".txt": "plaintext", ".cfg": "ini", ".env": "plaintext", ".lock": "plaintext",
}  # fmt: skip
_BY_NAME = {"dockerfile": "dockerfile", "makefile": "makefile", "requirements.txt": "plaintext"}

# Languages Nodecraft will analyse for dependencies in later milestones.
ANALYSABLE = {"python", "javascript", "typescript", "html", "css", "json", "yaml"}


def detect_language(path: str) -> str:
    p = PurePosixPath(path)
    return _BY_NAME.get(p.name.lower()) or _BY_EXT.get(p.suffix.lower(), "plaintext")


def looks_binary(sample: bytes) -> bool:
    return b"\x00" in sample[:8192]
