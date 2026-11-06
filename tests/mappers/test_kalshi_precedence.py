"""PASSYDSPRECISE must not displace a KXNFLPASSYDS ticker on a shared line."""

from types import SimpleNamespace

from mappers.exchanges.kalshi_precedence import keeps_existing


def _row(ticker, scope):
    return SimpleNamespace(kalshi_ticker=ticker, kalshi_scope=scope)


def test_precise_never_replaces_regular_ticker():
    reg = _row("KXNFLPASSYDS-X-175", "Passing Yards")
    assert keeps_existing(reg, _row("KXNFLPASSYDSPRECISE-X-175", "Passing Yards Range"))


def test_regular_replaces_precise_whatever_the_order():
    prec = _row("KXNFLPASSYDSPRECISE-X-175", "Passing Yards Range")
    assert not keeps_existing(prec, _row("KXNFLPASSYDS-X-175", "Passing Yards"))


def test_row_without_ticker_takes_precise():
    assert not keeps_existing(_row(None, None), _row("P", "Passing Yards Range"))


def test_ordinary_scopes_keep_last_write_wins():
    assert not keeps_existing(_row("A", "Game"), _row("B", "Game"))
