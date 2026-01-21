"""Device-side service package."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APPS = ROOT / "apps"
if str(APPS) not in sys.path:
    sys.path.insert(0, str(APPS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
