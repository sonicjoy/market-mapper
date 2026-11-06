"""Kalshi anytime-goalscorer mapper.

Maps Kalshi goalscorer tickers onto Optic fixtures by reusing each team's
player codes from previous games, and learns new codes through a Slack review
loop. Entry point: ``python -m goalscorer <command>`` (see ``__main__``).
Runbook: ``docs/goalscorer-mapper.md``.
"""
