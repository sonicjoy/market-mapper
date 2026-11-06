"""One-shot activate of a named mapping rule-set already in BQ.

Legacy tip tool (retiring); not a way to ship mapping. New rules go in code.

Does not seed. Console Parity reseed stays test-only. First prod tip:

    $env:GCP_PROJECT = "rs-marketmaking"
    python -m BigQuery.activate_mapping_rule_set --rule-set-id S0_xxxx --i-mean-it
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from BigQuery.client import ro_client
from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.store import ProposalStore

_TEST_PROJECT = "marketmaking-test"


def activate_named_rule_set(
    store: ProposalStore,
    rule_set_id: str,
    *,
    actor_subject: str,
) -> dict[str, Any]:
    """Activate ``rule_set_id`` and append ``rule_set_activated``.

    No-op when the served tip is already ``rule_set_id``.
    """
    if store.get_receipt(rule_set_id) is None:
        raise KeyError(rule_set_id)
    previous = store.current_rule_set_id
    if store.activated_rule_set_id == rule_set_id:
        return {
            "rule_set_id": rule_set_id,
            "previous_rule_set_id": previous,
            "already_active": True,
        }
    store.activate(rule_set_id)
    store.append_audit(
        {
            "request_id": f"cli-activate:{rule_set_id}",
            "event_type": "rule_set_activated",
            "proposal_id": None,
            "rule_set_id": rule_set_id,
            "previous_rule_set_id": previous,
            "expected_rule_set_id": previous,
            "actor_subject": actor_subject,
            "actor_role": "service",
            "artifact_type": "rule_set",
            "league": None,
            "status": "activated",
            "reason_code": "cli_activate",
        }
    )
    return {
        "rule_set_id": rule_set_id,
        "previous_rule_set_id": previous,
        "already_active": False,
    }


def _actor_subject() -> str:
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    return f"cli:{user}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rule-set-id", required=True, help="Existing S0_* or P_* id")
    parser.add_argument(
        "--i-mean-it",
        action="store_true",
        help="Required confirmation; refuses otherwise",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.i_mean_it:
        print("refusing: pass --i-mean-it", file=sys.stderr)
        return 2
    project = (os.environ.get("GCP_PROJECT") or "").strip()
    if not project:
        print("GCP_PROJECT is required", file=sys.stderr)
        return 2
    environment = "test" if project == _TEST_PROJECT else "prod"
    store = BigQueryStore(
        ro_client(),
        environment=environment,
        allow_activate=True,
    )
    try:
        result = activate_named_rule_set(
            store,
            args.rule_set_id,
            actor_subject=_actor_subject(),
        )
    except KeyError:
        print(f"unknown rule_set_id={args.rule_set_id}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    state = "already active" if result["already_active"] else "activated"
    print(f"{result['rule_set_id']} {state} (previous={result['previous_rule_set_id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
