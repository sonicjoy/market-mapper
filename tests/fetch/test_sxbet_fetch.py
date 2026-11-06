"""fetch.sxbet: page the public /markets/active book into sxbet_markets.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fetch import sxbet


class _Resp:
    def __init__(self, body: dict, status: int = 200) -> None:
        self._body, self.status_code = body, status

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise sxbet.requests.HTTPError(str(self.status_code))


class _Session:
    """Serves pages keyed by paginationKey; records the params it was asked for."""

    def __init__(self, pages: dict[str | None, dict]) -> None:
        self.pages, self.calls = pages, []

    def get(self, url: str, params: dict, timeout: int) -> _Resp:
        self.calls.append(dict(params))
        return _Resp(self.pages[params.get("paginationKey")])


def _page(markets: list[dict], next_key: str | None) -> dict:
    return {"status": "success", "data": {"markets": markets, "nextKey": next_key}}


def test_fetch_all_pages_until_no_next_key() -> None:
    s = _Session({None: _page([{"marketHash": "0x1"}], "k2"), "k2": _page([{"marketHash": "0x2"}], None)})
    assert [m["marketHash"] for m in sxbet.fetch_all(s)] == ["0x1", "0x2"]  # type: ignore[arg-type]
    assert all(c["pageSize"] == 100 for c in s.calls)


def test_an_empty_page_with_a_next_key_still_ends() -> None:
    s = _Session({None: _page([], "k2"), "k2": _page([{"marketHash": "0x2"}], None)})
    assert len(sxbet.fetch_all(s)) == 1  # type: ignore[arg-type]


def test_max_items_caps_the_fetch() -> None:
    s = _Session({None: _page([{"marketHash": "0x1"}, {"marketHash": "0x2"}], "k2")})
    assert len(sxbet.fetch_all(s, max_items=1)) == 1  # type: ignore[arg-type]


def test_an_error_body_is_retried_then_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sxbet.time, "sleep", lambda _s: None)
    s = _Session({None: {"status": "failure", "data": {}}})
    with pytest.raises(RuntimeError, match="failed after 3 tries"):
        sxbet.fetch_all(s)  # type: ignore[arg-type]
    assert len(s.calls) == 3


def test_write_jsonl_one_row_per_line(tmp_path: Path) -> None:
    path = sxbet.write_jsonl([{"marketHash": "0x1"}, {"marketHash": "0x2"}], tmp_path)
    assert path.name == "sxbet_markets.jsonl"
    assert [json.loads(line)["marketHash"] for line in path.read_text().splitlines()] == ["0x1", "0x2"]
