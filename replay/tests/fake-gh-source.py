"""A fake gh that answers GitHub's API for the source of a replay from $FAKE_GH_API, and refuses
every call but a plain GET, so that a script that would write to the source fails its test."""

import os
import re
import sys
from pathlib import Path


def append(variable, line):
    with Path(os.environ[variable]).open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def refuse(*words):
    text = " ".join(words)
    append("FAKE_GH_REFUSED", text)
    print(f"fake gh: refused: {text}", file=sys.stderr)
    sys.exit(1)


def main(args):
    append("FAKE_GH_LOG", " ".join(args))
    if not args or args[0] != "api":
        refuse(*args)
    method, endpoint = "GET", ""
    rest = iter(args[1:])
    for arg in rest:
        if arg in ("-X", "--method"):
            method = next(rest, "")
        elif arg.startswith("-X"):
            method = arg.removeprefix("-X")
        elif arg.startswith("--method="):
            method = arg.removeprefix("--method=")
        elif arg.startswith("-"):
            refuse(f"option {arg}")
        else:
            endpoint = arg
    if method != "GET":
        refuse(f"{method} {endpoint}")
    api = Path(os.environ["FAKE_GH_API"])
    path = endpoint.partition("?")[0].replace("/", "_")
    # The last page= of the query counts, as a greedy match finds it.
    page = re.match(r".*[?&]page=([0-9]*)", endpoint)
    if page:
        name = api / f"{path}-{page[1]}.json"
        sys.stdout.buffer.write(name.read_bytes() if name.is_file() else b"[]\n")
        return
    name = api / f"{path}.json"
    if not name.is_file():
        print('{"message": "Not Found"}')
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        sys.exit(1)
    sys.stdout.buffer.write(name.read_bytes())


main(sys.argv[1:])
