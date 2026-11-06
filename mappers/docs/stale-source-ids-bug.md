# Stale Optic PX source_ids

## The bug

`verify_source_ids` hard-raises when Optic's PX `selection_id` doesn't
match our `px_line_id`, but it doesn't distinguish between a genuine
mapping disagreement and Optic holding a stale reference to a PX
selection that no longer exists.

## Concrete example (2026-03-14 23:45 fetch)

Optic odd:

    optic_id: 19370-30354-2026-03-14:player_rebounds:kel_el_ware_under_8_5
    source_ids:
      Prophet X:
        event_id: "20023437"
        selection_id: "7c9666cfe3792a4a7c7092fe53aa708e"

Our pipeline matched:

    px_line_id: "10637b50b97c9e956050fdd72d6b67f3"

from PX market 730003207 ("Kel'el Ware Rebounds"), the "under 8.5"
selection.

The `selection_id` Optic carries (`7c9666cf...`) does not exist anywhere
in the current PX data.  PX has three separate "Kel'el Ware Rebounds"
markets (ids 730003207, 1500019855, 1500019856) for the same event
20023437 — PX likely regenerated or replaced the market, issuing new
`line_id` values, but Optic still references the old one.

## Why it crashes

In `optic.py` `verify_source_ids` (line 374-380), the PX branch does a
straight equality check:

```python
if optic_px_id != row.px_line_id:
    raise ValueError(...)
```

The Kalshi branch already has stale-detection logic (checking whether
the ticker date matches the fixture date, classifying mismatches into
stale / disambiguation / fixture-miss / not-in-data buckets).  The PX
branch has no equivalent — any mismatch is treated as fatal.

## Diagnosis

Our mapping is correct.  The raise is a false positive.  Optic's
`selection_id` is not present in our current PX data — we don't know
why (PX may have regenerated the market, or our fetch may not have
returned it), but the effect is the same: we can't cross-check.
This is no worse than the `px_novel` case where Optic has no PX
source_id at all and we already trust our mapping without
confirmation.

## Fix (2026-03-17, commit 16a48f8)

`verify_source_ids` now triages PX mismatches into three sub-cases
(see the comment block in `optic.py` for the full 3+3 case
breakdown):

  a. Optic's ID not in our PX data — warn, keep our mapping.
  b. Optic's ID is a sup_moneyline sibling of ours (same entity,
     stat, line, game) — warn, keep our total selection.  Optic
     picks total 99.9% of the time; the rare sup_moneyline
     reference is unexplained but harmless.  Always using our own
     total keeps output deterministic.
  c. Otherwise — genuine disagreement, still raises.

Case (b) was discovered during the same investigation: Optic
occasionally references the sup_moneyline PX market object instead
of the total for the same prop (e.g. Luka Garza Rebounds Over 3.5,
2026-03-16 fetch).
