#!/usr/bin/env python3
"""Shared hashing, containment, and atomic-write helpers for BFG scripts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def photo_set_digest(entries: Iterable[dict[str, Any]]) -> str:
    normalized = [
        {
            "sequence": int(entry["sequence"]),
            "relative_path": str(entry["relative_path"]).replace("\\", "/"),
            "bytes": int(entry["bytes"]),
            "sha256": str(entry["sha256"]).casefold(),
        }
        for entry in entries
        if str(entry.get("status", "")) != "missing"
    ]
    return sha256_json(normalized)


def contained_path(root: Path, relative: str, *, label: str = "path") -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not relative.strip():
        raise ValueError(f"Unsafe {label}: {relative!r}")
    root_resolved = root.resolve()
    resolved = (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"{label} escapes its root: {relative!r}") from exc
    return resolved


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
