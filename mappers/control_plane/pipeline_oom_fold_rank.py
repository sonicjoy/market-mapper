"""GKE CronJob entrypoint for release 068 G2 fold+rank.

Usage:
    python -m mappers.control_plane.pipeline_oom_fold_rank
"""

from __future__ import annotations

import sys

from BigQuery.oom_fold_rank import main

if __name__ == "__main__":
    sys.exit(main())
