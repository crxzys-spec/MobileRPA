import sys

from mrpa.cli.handlers import main as run_main
from shared.errors import AdbError


def main():
    return run_main()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AdbError as exc:
        print("error:", exc, file=sys.stderr)
        sys.exit(1)
