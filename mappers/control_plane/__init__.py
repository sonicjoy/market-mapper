"""M3a dual-write control plane (entity_alias proposals).

Retired: the console / control plane (incl. Mapper Chat) is not a path
for shipping mapping. Mapping rules are code-owned and ship by MR.
"""

from mappers.control_plane.service import ProposalService

__all__ = ["ProposalService"]
