"""Copy a data directory from a remote VM to the local repo.

Usage:
    python -m scripts.copy_data_dir [-f] <vm> <data_dir>

Example:
    python -m scripts.copy_data_dir market-mapping-test data/2026-03-25/12_27
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy a data dir from a remote VM")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Remove existing local directory before copying")
    parser.add_argument("vm")
    parser.add_argument("data_dir", type=Path)
    args = parser.parse_args()

    vm: str = args.vm
    data_dir: Path = args.data_dir

    # Remote base is ~/mmmapper/<data_dir>
    remote_base = f"~/mmmapper/{data_dir.parent}"
    dir_name = data_dir.name

    local_parent = Path.cwd() / data_dir.parent
    local_target = local_parent / dir_name

    if local_target.exists():
        if not args.force:
            print(f"Already exists: {local_target}", file=sys.stderr)
            print("Use --overwrite (mise) or -f (direct) to overwrite.", file=sys.stderr)
            sys.exit(1)
        shutil.rmtree(local_target)

    # Ensure local parent directory exists
    local_parent.mkdir(parents=True, exist_ok=True)

    cmd = (
        f'ssh {vm} "tar czf - -C {remote_base} {dir_name}"'
        f" | tar xzf - -C {local_parent}"
    )
    print(f"Copying {vm}:~/mmmapper/{data_dir} -> {local_parent / dir_name}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print("Transfer failed.", file=sys.stderr)
        sys.exit(result.returncode)
    print("Done.")


if __name__ == "__main__":
    main()
