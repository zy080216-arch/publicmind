"""Command-line entry point for the runnable MVP slice."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import List

from .pipeline import IngestPipeline
from .store import Repository


async def _build(args: argparse.Namespace) -> int:
    repository = Repository(args.db)
    try:
        person = repository.create_person(args.name)
        pipeline = IngestPipeline(repository)
        results = []
        for url in args.url:
            try:
                result = await pipeline.ingest(person.id or "", url)
                results.append(
                    {
                        "url": url,
                        "document_id": result.document_id,
                        "inserted": result.inserted,
                        "status": "completed",
                    }
                )
            except Exception as exc:
                results.append({"url": url, "status": "failed", "error": str(exc)})
        vault_dir, zip_path = pipeline.export(person.id or "", args.output)
        print(
            json.dumps(
                {
                    "person_id": person.id,
                    "vault": str(vault_dir),
                    "zip": str(zip_path),
                    "sources": results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if any(item["status"] == "completed" for item in results) else 1
    finally:
        repository.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publicmind", description="Build a source-first Obsidian knowledge vault")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="fetch URLs and export an Obsidian Vault")
    build.add_argument("--name", required=True, help="public person's name")
    build.add_argument("--url", action="append", required=True, help="public source URL; repeat for multiple URLs")
    build.add_argument("--db", default="data/publicmind.db", help="SQLite database path or sqlite:/// URL")
    build.add_argument("--output", default="data/exports", help="Vault and zip output directory")
    return parser


def main(argv: List[str] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        return asyncio.run(_build(args))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

