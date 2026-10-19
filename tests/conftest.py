"""Unit tests for re-ddns modules that need no Reflex, Docker or network.

The collections tests also use the app-side library from the sibling
``reflex_ddns_auth`` checkout (or ``REFLEX_DDNS_AUTH_PATH``).
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for candidate in (os.environ.get("REFLEX_DDNS_AUTH_PATH"), ROOT.parent / "reflex_ddns_auth"):
    if candidate and Path(candidate).is_dir():
        sys.path.insert(0, str(candidate))
        break
