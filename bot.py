import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APPS = ROOT / "apps"
if str(APPS) not in sys.path:
    sys.path.insert(0, str(APPS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mrpa.cli import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
