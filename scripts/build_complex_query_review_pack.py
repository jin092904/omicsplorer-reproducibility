#!/usr/bin/env python3
"""Create session Markdown, GEO link pages, and compact score sheets."""
from __future__ import annotations

import argparse
from pathlib import Path

from genofinder_eval.external.complex_query_review_pack import export_review_pack


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = export_review_pack(
        template=args.template.resolve(),
        manifest_path=args.manifest.resolve(),
        output_dir=args.output.resolve(),
    )
    print(
        f"created review pack: rows={manifest['row_count']} "
        f"queries={manifest['query_count']} sessions={len(manifest['session_counts'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
