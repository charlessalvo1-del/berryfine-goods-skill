#!/usr/bin/env python3
"""Create or verify an immutable hash inventory for one BFG intake."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bfg_integrity import contained_path, sha256_file, sha256_json


class SealError(ValueError):
    """Raised when an audit seal is incomplete, changed, or unsafe."""


def atomic_create(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise SealError(f"Refusing to overwrite existing audit seal: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def entries(root: Path, relative_paths: list[str]) -> list[dict[str, Any]]:
    if not relative_paths:
        raise SealError("At least one artifact is required")
    result = []
    seen: set[str] = set()
    for relative in relative_paths:
        normalized = relative.replace("\\", "/")
        if normalized.casefold() in seen:
            raise SealError(f"Repeated artifact: {relative}")
        seen.add(normalized.casefold())
        path = contained_path(root, normalized, label="audit artifact")
        if not path.is_file():
            raise SealError(f"Missing audit artifact: {normalized}")
        result.append({"relative_path": normalized, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    result.sort(key=lambda item: item["relative_path"].casefold())
    return result


def create(args: argparse.Namespace) -> dict[str, Any]:
    artifacts = entries(args.root, args.artifact)
    seal: dict[str, Any] = {
        "version": 1,
        "client_id": args.client_id,
        "intake_id": args.intake_id,
        "pipeline_version": args.pipeline_version,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "root": str(args.root.resolve()),
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "artifact_root_digest": sha256_json(artifacts),
    }
    seal["seal_digest"] = sha256_json(seal)
    atomic_create(args.output, seal)
    return seal


def verify(args: argparse.Namespace) -> dict[str, Any]:
    seal = json.loads(args.seal.read_text(encoding="utf-8-sig"))
    expected_digest = seal.pop("seal_digest", "")
    if expected_digest != sha256_json(seal):
        raise SealError("Audit seal JSON has been changed")
    root = Path(str(seal.get("root", "")))
    current = entries(root, [entry["relative_path"] for entry in seal.get("artifacts", [])])
    if current != seal.get("artifacts") or sha256_json(current) != seal.get("artifact_root_digest"):
        raise SealError("One or more sealed artifacts changed")
    return {"version": 1, "status": "PASS", "client_id": seal.get("client_id", ""), "intake_id": seal.get("intake_id", ""), "artifact_count": len(current), "seal_sha256": sha256_file(args.seal)}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Create or verify a BFG intake audit seal.")
    commands = root.add_subparsers(dest="command", required=True)
    create_parser = commands.add_parser("create")
    create_parser.add_argument("--root", required=True, type=Path)
    create_parser.add_argument("--client-id", required=True)
    create_parser.add_argument("--intake-id", required=True)
    create_parser.add_argument("--pipeline-version", required=True)
    create_parser.add_argument("--artifact", action="append", required=True)
    create_parser.add_argument("--output", required=True, type=Path)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--seal", required=True, type=Path)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        result = create(args) if args.command == "create" else verify(args)
        print(json.dumps(result if args.command == "verify" else {"status": "PASS", "artifact_count": result["artifact_count"], "seal": str(args.output)}, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, SealError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
