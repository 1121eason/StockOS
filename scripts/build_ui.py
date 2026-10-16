#!/usr/bin/env python3
"""Validate and package the local UI without Node, network access or database reads."""

import hashlib
import json
import shutil
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ("index.html", "styles.css", "app.js", "domain.mjs", "favicon.svg")


class AssetParser(HTMLParser):
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key.startswith("on") or key == "style":
                raise ValueError("Inline handlers/styles are not allowed")
            if key == "src" or (tag == "link" and key == "href"):
                if value is None or not value.startswith("/") or value[1:] not in ASSETS:
                    raise ValueError(f"Unexpected external asset: {value}")


def main() -> None:
    output = ROOT / "dist/stockos-ui"
    output.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in ASSETS:
        source = ROOT / "ui" / name
        content = source.read_text(encoding="utf-8")
        if name == "index.html":
            AssetParser().feed(content)
        manifest[name] = hashlib.sha256(source.read_bytes()).hexdigest()
        shutil.copy2(source, output / name)
    data = json.loads((ROOT / "ui/fixtures/demo.json").read_text(encoding="utf-8"))
    assert data["mode"] == "demo" and data["snapshot"]["price"] is None
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("UI assets validated and packaged: dist/stockos-ui")
    print("Run the Python server for /api support; this package is not a standalone website.")


if __name__ == "__main__":
    main()
