"""Harmless blocked Python descendants used only by the owned offline job test."""

import subprocess
import sys
import time


def main() -> None:
    """Create exactly two descendant levels with no inherited credential configuration."""
    stage = sys.argv[1] if len(sys.argv) == 2 else "worker"
    if stage in {"worker", "child"}:
        child = "child" if stage == "worker" else "grandchild"
        with subprocess.Popen([sys.executable, "-I", __file__, child]) as process:
            process.wait()
    else:
        time.sleep(60)


if __name__ == "__main__":
    main()
