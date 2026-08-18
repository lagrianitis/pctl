"""Console-script entry point."""

from __future__ import annotations

import os
import sys


def main() -> None:
    from .cli import cli

    try:
        cli.main(prog_name="pctl")
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130) from None
    except BrokenPipeError:
        # A downstream consumer (head, less) closed the pipe. Point stdout at
        # /dev/null so the interpreter's shutdown flush cannot raise again.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(141) from None


if __name__ == "__main__":
    main()
