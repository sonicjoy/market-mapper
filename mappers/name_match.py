"""String-distance primitives for name matching.

Split out of ``mappers/shared.py`` because that module sits against the
500-line file guard: adding one book's provenance fields to
``CanonicalRow`` breached it, and this is the piece with no dependency on
anything else in there.  ``normalize_player_name`` is the natural next
tenant, once it can be split under the 50-line function guard.
"""


def levenshtein(a: str, b: str) -> int:
    """Levenshtein edit distance between two strings.

    Used by the player name normalization diagnostic to find near-
    matches between exchange orphans and Optic names.  Pure stdlib,
    O(len(a) * len(b)) time and O(min(len(a), len(b))) space.
    """
    if len(a) < len(b):
        return levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,      # deletion
                curr[j] + 1,           # insertion
                prev[j] + (ca != cb),  # substitution
            ))
        prev = curr
    return prev[-1]
