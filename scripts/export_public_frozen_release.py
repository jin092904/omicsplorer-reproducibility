#!/usr/bin/env python3
"""Export a validated private frozen run through the reviewed public boundary."""

from __future__ import annotations

import argparse
from pathlib import Path

from genofinder_eval.frozen_release_public import export_public_frozen_release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-release", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--gdc-open-review", type=Path)
    args = parser.parse_args()
    manifest = export_public_frozen_release(
        args.private_release,
        args.output_dir,
        gdc_open_review=args.gdc_open_review,
    )
    print(
        f"public projection {manifest['projection_status']}: "
        f"{manifest['counts']['observations']} observations; "
        f"publication_ready={manifest['publication_ready']}"
    )
    for blocker in manifest["blockers"]:
        print(f"BLOCKER: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
