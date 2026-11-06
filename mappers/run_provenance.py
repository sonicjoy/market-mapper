"""Run-level provenance stamped onto market_mapping rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from mappers.seed.audit import git_commit_short, new_mapping_run_id
from mappers.seed.sot import load_snapshot

MAPPING_LOGIC_VERSION = "pipeline_v1"


@dataclass(frozen=True)
class RunProvenance:
    mapping_run_id: str
    mapper_git_commit: str | None
    mapping_logic_version: str
    mapped_at: str
    rule_set_id: str | None

    def as_dict(self) -> dict:
        return {
            "mapping_run_id": self.mapping_run_id,
            "mapper_git_commit": self.mapper_git_commit,
            "mapping_logic_version": self.mapping_logic_version,
            "mapped_at": self.mapped_at,
            "rule_set_id": self.rule_set_id,
        }


def new_run_provenance() -> RunProvenance:
    rule_set_id: str | None = load_snapshot().rule_set_id
    return RunProvenance(
        mapping_run_id=new_mapping_run_id(),
        mapper_git_commit=git_commit_short(),
        mapping_logic_version=MAPPING_LOGIC_VERSION,
        mapped_at=datetime.now(UTC).isoformat(),
        rule_set_id=rule_set_id,
    )
