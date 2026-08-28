#!/usr/bin/env python3
"""Freeze the live Sol4 contract from a clean OmicsPlorer product checkout."""

from __future__ import annotations

import argparse
from pathlib import Path

from genofinder_eval.metadata_contract import freeze_contract

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "protocols/metadata-enrichment-pilot-v1/frozen-contract"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11437")
    parser.add_argument("--model-tag", default="gemma4:31b")
    parser.add_argument("--gpu-index", type=int, default=5)
    args = parser.parse_args()

    manifest = freeze_contract(
        product_root=args.product_root.resolve(),
        output_dir=args.output_dir.resolve(),
        ollama_url=args.ollama_url,
        model_tag=args.model_tag,
        gpu_index=args.gpu_index,
    )
    print(f"status={manifest['status']}")
    print(f"product_git_commit={manifest['product_git_commit']}")
    print(f"output_dir={args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
