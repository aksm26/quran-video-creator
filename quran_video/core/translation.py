"""Cut a verse's translation into pieces that follow the Arabic parts.

Translations aren't word-aligned with the Arabic, so cut points are chosen at punctuation nearest to where each
part ends in the Arabic (by share of letters). Falls back to the nearest word if there is no punctuation."""

import unicodedata

PUNCT = tuple(",;:.!?،؛؟、。，；：！？—)]”’»\"'")


def letter_weight(arabic: str) -> int:
    return sum(1 for c in arabic if unicodedata.category(c).startswith("L")) or 1


def split_translation(text: str, weights: list[int]) -> list[str]:
    """len(weights) pieces; joining them (with spaces, or nothing for unspaced scripts) gives back `text`."""
    n = len(weights)
    spaced = " " in text.strip()
    tokens = text.split() if spaced else list(text.strip())
    if n <= 1 or len(tokens) < n:
        return [text] + [""] * (n - 1) if n else []
    total, acc, cuts = sum(weights), 0, []
    for k in range(n - 1):
        acc += weights[k]
        lo = (cuts[-1] if cuts else 0) + 1  # cut = number of tokens in the pieces so far
        hi = len(tokens) - (n - 1 - k)
        want = min(max(round(acc / total * len(tokens)), lo), hi)
        window = max(3, round(len(tokens) * 0.2))
        punct = [i for i in range(lo, hi + 1) if tokens[i - 1].endswith(PUNCT) and abs(i - want) <= window]
        cuts.append(min(punct, key=lambda i: abs(i - want)) if punct else want)
    sep = " " if spaced else ""
    bounds = [0, *cuts, len(tokens)]
    return [sep.join(tokens[a:b]) for a, b in zip(bounds, bounds[1:])]
