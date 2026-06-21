from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}


def collect_image_paths(image_root: Path) -> list[str]:
    if not image_root.exists():
        return []
    items: list[str] = []
    parent = image_root.parent
    for path in sorted(image_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        relative = path.relative_to(parent)
        items.append("/" + str(relative).replace("\\", "/"))
    return items


def build_manifest(image_root: Path) -> dict[str, object]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "images": collect_image_paths(image_root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an image path manifest for backend consumption.")
    parser.add_argument("--image-root", type=Path, required=True, help="Directory containing the public images tree.")
    parser.add_argument("--output", type=Path, required=True, help="Path of the manifest JSON to write.")
    args = parser.parse_args()

    payload = build_manifest(args.image_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {len(payload['images'])} image paths to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
