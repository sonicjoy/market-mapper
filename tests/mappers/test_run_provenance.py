"""Run-level provenance stamped onto mapping records."""

from mappers.run_provenance import MAPPING_LOGIC_VERSION, new_run_provenance
from mappers.seed.sot import load_snapshot


def test_new_run_provenance_fields():
    """Provenance stamps the activated tip's rule_set_id, never None."""
    prov = new_run_provenance()
    d = prov.as_dict()
    assert d["mapping_run_id"]
    assert d["mapping_logic_version"] == MAPPING_LOGIC_VERSION
    assert d["mapped_at"]
    assert d["rule_set_id"] == load_snapshot().rule_set_id
