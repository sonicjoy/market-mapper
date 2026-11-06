"""Cross-source validation of the Polymarket position<->token pairing.

Split out of ``load_polymarket_position_bridge`` so the loader keeps to building and
merging rows while the "can this pairing be trusted?" decision — the safety-critical
part — lives on its own and can be read and tested without the BigQuery machinery
around it.

The bridge pairs ``position_id[i] <-> clob_token_id[i] <-> outcome_label[i]`` off ONE
Gamma record's array order. Getting that wrong flips the traded side downstream, so the
pairing is checked against independent sources and fails closed.
"""


def _norm(s) -> str:
    """Normalize an outcome/side label for comparison (case- and whitespace-insensitive)."""
    return (str(s) if s is not None else "").strip().lower()


def flip_guard_reason(m, combos_outcome_by_pid, optic_side_by_clob) -> str | None:
    """Return a reason string if this market's position<->token pairing can't be trusted.

    The bridge pairs ``position_id[i] <-> clob_token_id[i] <-> outcome_label[i]`` from
    ONE Gamma record's array order. A silent reorder pairs a position with the wrong
    token, which flips the traded side downstream (catastrophic). So we cross-check
    each pairing against INDEPENDENT sources and fail closed on any disagreement:

    * Tier 1 (``combos_outcome_by_pid``) — combos-rfq-api's own position_id -> outcome,
      a different system from Gamma. A shared position_id whose label disagrees means
      the two sources order outcomes differently -> untrustworthy.
    * Tier 2 (``optic_side_by_clob``) — OpticOdds' independent clob_token_id -> over/under
      side (the exact mapping the maker prices off). For totals legs, the Gamma
      outcome_label paired with a token must match optic's side for that token.

    Absence of a map entry is a coverage gap, NOT a disagreement — it is not a reason
    to drop (uncovered legs aren't priced, so they can't flip). Either map being
    ``None`` disables that tier (e.g. historical backfill, where combos no longer lists
    the settled leg).
    """
    pids = m["position_ids"]
    clobs = m["clob_token_ids"]
    outs = m["outcomes"]
    for i, pid in enumerate(pids):
        label = outs[i] if i < len(outs) else ""
        nlabel = _norm(label)
        if combos_outcome_by_pid is not None:
            combo_label = combos_outcome_by_pid.get(pid)
            if combo_label is not None and _norm(combo_label) != nlabel:
                return f"combos_outcome_disagree pid={pid} gamma={label!r} combos={combo_label!r}"
        if optic_side_by_clob is not None and nlabel in ("over", "under"):
            clob = clobs[i] if i < len(clobs) else ""
            optic_side = optic_side_by_clob.get(clob)
            if optic_side is not None and _norm(optic_side) != nlabel:
                return f"optic_side_disagree clob={clob} gamma={label!r} optic={optic_side!r}"
    return None
