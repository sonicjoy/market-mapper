"""BigQuery fragments for crypto.com RFQ NX symbols.

The Java maker (2026-09+) stores combo legs in ``metadata.quote_details``
(JSON string: ``qr.symbols[].legs[].symbol``). ``reason_detail`` is now
``{n} of {m} legs mapped, minimum is 2`` — the old
``no mapping for symbol NX…`` regex returns zero rows.

Legacy RFQs may still carry the old string or a structured ``legs`` row.
"""

from __future__ import annotations

from mappers.control_plane.rfq_latest_sql import (
    CRYPTO_PLATFORMS,
    platform_in,
    recent_window,
    unmapped_failed,
)

_LEGACY_SYMBOL = """
regexp_extract(
  json_value(r.metadata, '$.reason_detail'),
  r'no mapping for symbol (NX\\.[^ ]+)'
)"""

_QUOTE_DETAIL_SYMBOL = "json_value(leg, '$.symbol')"

_STRUCTURED_LEG_SYMBOL = "json_value(l.platform_mapping, '$.symbol')"

def _crypto_rfq_where(hours: int) -> str:
    """crypto.com mapping failures updated in the last ``hours`` (clustered + partition-bounded)."""
    return "\n" + "\nand ".join([platform_in(CRYPTO_PLATFORMS), unmapped_failed(), recent_window(hours)])

_QUOTE_DETAILS_FROM = """
from `{project}.reporting_us.rfq_latest` r,
unnest(json_query_array(
  safe.parse_json(json_value(r.metadata, '$.quote_details')),
  '$.qr.symbols'
)) as combo,
unnest(json_query_array(combo, '$.legs')) as leg"""


def crypto_rfq_symbol_rows_sql(*, hours: int = 3) -> str:
    """Union of quote_details legs, legacy reason_detail, and structured legs."""
    where = _crypto_rfq_where(int(hours))
    quote = f"""
  select
    {_QUOTE_DETAIL_SYMBOL} as symbol,
    r.last_updated,
    r.external_rfq_id
{_QUOTE_DETAILS_FROM}
  where {where}
    and {_QUOTE_DETAIL_SYMBOL} is not null
    and {_QUOTE_DETAIL_SYMBOL} not like 'NX.F.OPT.COMBOS%'"""  # nosec B608
    legacy = f"""
  select
    {_LEGACY_SYMBOL} as symbol,
    r.last_updated,
    r.external_rfq_id
  from `{{project}}.reporting_us.rfq_latest` r
  where {where}
    and {_LEGACY_SYMBOL} is not null"""  # nosec B608
    structured = f"""
  select
    {_STRUCTURED_LEG_SYMBOL} as symbol,
    r.last_updated,
    r.external_rfq_id
  from `{{project}}.reporting_us.rfq_latest` r
  left join unnest(r.legs) as l
  where {where}
    and {_STRUCTURED_LEG_SYMBOL} is not null"""  # nosec B608
    return f"(\n{quote}\n  union all\n{legacy}\n  union all\n{structured}\n)"  # nosec B608


def crypto_rfq_mf_cte(*, hours: int = 3) -> str:
    """``crypto_mf`` CTE body used by harvest and console inventory.

    Dedup ``(symbol, rfq)`` so quote_details ∪ legacy ∪ structured does not
    triple-count the same failed combo.
    """
    return f"""
crypto_mf as (
  select symbol, last_updated, external_rfq_id
  from {crypto_rfq_symbol_rows_sql(hours=int(hours))}
  where symbol is not null
  qualify row_number() over (
    partition by symbol, coalesce(external_rfq_id, '')
    order by last_updated desc
  ) = 1
),
"""  # nosec B608
