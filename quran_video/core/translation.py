"""Cut a verse's translation into pieces that follow the Arabic parts.

Translations aren't word-aligned with the Arabic, so cut points are chosen at punctuation nearest to where each
part ends in the Arabic (by share of letters). Falls back to the nearest word if there is no punctuation."""

import unicodedata

PUNCT = tuple(",;:.!?،؛؟、。，；：！？—)]”’»\"'")
OPEN, CLOSE = "([{（【", ")]}）】"  # brackets only: quotes can span most of a verse


def letter_weight(arabic: str) -> int:
    return sum(1 for c in arabic if unicodedata.category(c).startswith("L")) or 1


def is_spaced(texts) -> bool:
    """Does this text (or any of these texts) separate its words with spaces? Unspaced scripts (Chinese,
    Japanese...) are cut between characters instead."""
    return any(" " in t.strip() for t in ([texts] if isinstance(texts, str) else texts))


def tokens(text: str, spaced: bool | None = None) -> tuple[list[str], str]:
    """The words of `text` (its characters for an unspaced script) and the separator that joins them back."""
    spaced = is_spaced(text) if spaced is None else spaced
    return (text.split(), " ") if spaced else (list(text.strip()), "")


def split_translation(text: str, weights: list[int]) -> list[str]:
    """len(weights) pieces; joining them (with spaces, or nothing for unspaced scripts) gives back `text`."""
    n = len(weights)
    toks, sep = tokens(text)
    if n <= 1 or len(toks) < n:
        return [text] + [""] * (n - 1) if n else []
    depth = [0]  # brackets still open after the first i tokens: never cut inside "[i.e., ...]" or "(...)"
    for t in toks:
        depth.append(depth[-1] + sum(t.count(c) for c in OPEN) - sum(t.count(c) for c in CLOSE))
    total, acc, cuts = sum(weights), 0, []
    for k in range(n - 1):
        acc += weights[k]
        lo = (cuts[-1] if cuts else 0) + 1  # cut = number of tokens in the pieces so far
        hi = len(toks) - (n - 1 - k)
        want = min(max(round(acc / total * len(toks)), lo), hi)
        window = max(3, round(len(toks) * 0.2))
        free = [i for i in range(lo, hi + 1) if depth[i] <= 0] or [want]
        punct = [i for i in free if toks[i - 1].endswith(PUNCT) and abs(i - want) <= window]
        cuts.append(min(punct or free, key=lambda i: abs(i - want)))
    bounds = [0, *cuts, len(toks)]
    return [sep.join(toks[a:b]) for a, b in zip(bounds, bounds[1:])]
