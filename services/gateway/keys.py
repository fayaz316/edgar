"""Create an API key.  uv run python -m services.gateway.keys NAME

Prints the key ONCE (give it to the caller) and the config entry to append to EA_API_KEYS.
Only the hash is ever stored; a lost key cannot be recovered, only replaced.
"""

from __future__ import annotations

import sys

from services.gateway.security import generate_key


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].replace("-", "").replace("_", "").isalnum():
        print(
            "usage: python -m services.gateway.keys NAME   (letters, digits, - and _ only)",
            file=sys.stderr,
        )
        return 2
    name = sys.argv[1]
    key, digest = generate_key()
    print(f"API key for {name} (shown once, store it safely):\n  {key}\n")
    print(f"Add to EA_API_KEYS (comma-separated):\n  {name}:{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
