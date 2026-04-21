import argparse
import json

from openbbq import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openbbq")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("command", choices=["version"])
    args = parser.parse_args(argv)
    if args.command == "version":
        payload = {"ok": True, "version": __version__}
        print(json.dumps(payload) if args.json_output else __version__)
        return 0
    return 2
