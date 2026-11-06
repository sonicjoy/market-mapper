"""GCP CLI helpers for fetch scripts."""

import sys


def gcloud_cmd(*args: str) -> list[str]:
    """Build a gcloud argv list that works on Windows and Unix.

    On Windows the Cloud SDK installs ``gcloud.cmd``; bare ``gcloud`` is
    not executable via subprocess without shell=True.
    """
    executable = "gcloud.cmd" if sys.platform == "win32" else "gcloud"
    return [executable, *args]
