"""Load merged crypto.com team-id aliases across all league configs."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from mappers.canonical_codes import names_close

_COMMENTED_CRYPTO_ID_RE = re.compile(
    r'crypto_id\s*=\s*\["(\d+)"\]\s*(?:#\s*(.+))?$',
    re.M,
)

_TEAM_PREFIXES = (
    "fk ",
    "kf ",
    "sk ",
    "fc ",
    "cf ",
    "sc ",
    "ac ",
    "as ",
    "us ",
    "nk ",
    "pfk ",
    "gnk ",
    "ks ",
    "sp ",
    "cs ",
    "cd ",
    "sv ",
    "sd ",
    "rc ",
)
_TEAM_SUFFIXES = (" fc", " fa", " fk", " cf", " sc", " ac", " sk")


def _ascii_fold(text: str) -> str:
    """Strip accents/diacritics so Győri ↔ gyori comparisons work."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_feed_team_name(name: str) -> str:
    """Normalize a crypto/Optic team display name for fuzzy comparison."""
    text = _ascii_fold(name.casefold().strip())
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    changed = True
    while changed and text:
        changed = False
        for prefix in _TEAM_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                changed = True
                break
        for suffix in _TEAM_SUFFIXES:
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
                changed = True
                break
    return text


def _name_tokens(name: str) -> tuple[str, ...]:
    return tuple(t for t in normalize_feed_team_name(name).split() if t)


def feed_team_names_match(left: str, right: str) -> bool:
    """Return True when two feed/Optic display names likely name the same team."""
    if left.casefold() == right.casefold():
        return True
    norm_left = normalize_feed_team_name(left)
    norm_right = normalize_feed_team_name(right)
    if norm_left and norm_left == norm_right:
        return True
    tokens_left = _name_tokens(left)
    tokens_right = _name_tokens(right)
    if not tokens_left or not tokens_right:
        return False
    shorter, longer = (
        (tokens_left, tokens_right) if len(tokens_left) <= len(tokens_right) else (tokens_right, tokens_left)
    )
    longer_set = set(longer)
    if not all(token in longer_set for token in shorter):
        return False
    if len(shorter) == 1:
        return len(shorter[0]) >= 3
    return True


def resolve_feed_name_to_crypto_id(
    name: str,
    name_to_id: dict[str, str],
    *,
    player: bool = False,
) -> str | None:
    """Resolve a feed display name to a crypto_id, exact then evidence-close."""
    if name in name_to_id:
        return name_to_id[name]
    folded = name.casefold()
    for feed_name, crypto_id in name_to_id.items():
        if feed_name.casefold() == folded:
            return crypto_id
    return _strict_lookup(name, name_to_id, player=player)


def resolve_feed_name_to_code(
    feed_name: str,
    candidates: dict[str, str],
    *,
    player: bool = False,
) -> str | None:
    """Map a FIX feed participant name to a canonical code (evidence-close)."""
    if feed_name in candidates:
        return candidates[feed_name]
    folded = feed_name.casefold()
    if folded in candidates:
        return candidates[folded]
    return _strict_lookup(feed_name, candidates, player=player)


def _strict_lookup(name: str, mapping: dict[str, str], *, player: bool) -> str | None:
    """Same person/club as `names_close` (no token-subset fuzzy)."""
    for candidate_name, value in mapping.items():
        if names_close(name, candidate_name, player=player):
            return value
    return None


def load_feed_name_to_crypto_id(path: Path) -> dict[str, str]:
    """Map crypto.com feed team display names to EXTERNAL_* id strings.

    Reads ``crypto_id = ["…"]  # Feed Name`` comment lines from one TOML.
    """
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    mapping: dict[str, str] = {}
    for match in _COMMENTED_CRYPTO_ID_RE.finditer(text):
        crypto_id, comment = match.group(1), match.group(2)
        if comment:
            mapping[comment.strip()] = crypto_id
    return mapping


def load_merged_name_to_crypto_id(
    config_dir: Path = Path("config"),
) -> dict[str, str]:
    """Merge feed display-name -> crypto_id maps from every league TOML."""
    merged: dict[str, str] = {}
    for path in sorted(config_dir.glob("*/team_aliases.toml")):
        merged.update(load_feed_name_to_crypto_id(path))
    return merged
