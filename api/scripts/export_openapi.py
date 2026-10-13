"""Write the API's OpenAPI document to api/openapi.json, the source of the web app's types.

    python scripts/export_openapi.py          # rewrite openapi.json
    python scripts/export_openapi.py --check  # exit 1 if openapi.json is stale

`web/` generates `lib/api/schema.ts` from this file with `npm run api:types`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from xmoney.main import create_app

_TARGET = Path(__file__).resolve().parent.parent / "openapi.json"


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if openapi.json is stale")
    args = parser.parse_args()
    rendered = render()
    if args.check:
        current = _TARGET.read_text() if _TARGET.exists() else ""
        if current != rendered:
            print("api/openapi.json is stale; run `make openapi`", file=sys.stderr)
            return 1
        return 0
    _TARGET.write_text(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
