"""
Copy the extraction engine from the FastAPI project into this app.

The FastAPI project (document-intelligence/app) is the source of
truth. Run this after changing the engine there:

    python sync_engine.py [path/to/document-intelligence/app]

Copies models, processors, services, core and config into
frappe_pi_validator/extraction/ and rewrites `app.` imports to
`frappe_pi_validator.extraction.`. The FastAPI web layer (api/,
main.py) is not copied.
"""

import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "app"
TARGET = HERE / "frappe_pi_validator" / "extraction"

PACKAGES = ["core", "models", "processors", "services"]
MODULES = ["config.py"]
IMPORT = re.compile(r"\b(from|import)\s+app(\.|\b)")


def rewrite(text: str) -> str:
    return IMPORT.sub(lambda m: f"{m.group(1)} frappe_pi_validator.extraction{m.group(2)}", text)


def main():
    if not (SOURCE / "services").is_dir():
        sys.exit(f"Engine not found at {SOURCE}")

    if TARGET.exists():
        shutil.rmtree(TARGET)

    TARGET.mkdir(parents=True)
    (TARGET / "__init__.py").write_text(
        '"""Document extraction engine (synced from document-intelligence/app by sync_engine.py; do not edit here)."""\n'
    )

    count = 0

    for name in PACKAGES:
        for path in (SOURCE / name).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            destination = TARGET / path.relative_to(SOURCE)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rewrite(path.read_text()))
            count += 1

    for name in MODULES:
        (TARGET / name).write_text(rewrite((SOURCE / name).read_text()))
        count += 1

    print(f"Synced {count} files from {SOURCE} to {TARGET}")


if __name__ == "__main__":
    main()
