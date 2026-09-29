"""Place-of-articulation viseme groups (IPA → CV search key). No detector here."""

from __future__ import annotations

from typing import Iterable, List

# IPA 2020 pulmonic columns used as viseme bins
VISEME_OF = {
    "p": "bilabial", "b": "bilabial", "m": "bilabial", "ɸ": "bilabial", "β": "bilabial",
    "f": "labiodental", "v": "labiodental",
    "θ": "dental", "ð": "dental",
    "t": "alveolar", "d": "alveolar", "n": "alveolar", "s": "alveolar",
    "z": "alveolar", "l": "alveolar", "r": "alveolar",
    "ʃ": "postalveolar", "ʒ": "postalveolar", "tʃ": "postalveolar", "dʒ": "postalveolar",
    "j": "palatal",
    "k": "velar", "ɡ": "velar", "ŋ": "velar",
    "h": "glottal",
}


def viseme_of(ipa: str) -> str:
    if ipa in VISEME_OF:
        return VISEME_OF[ipa]
    if ipa and ipa[0] in VISEME_OF:
        return VISEME_OF[ipa[0]]
    return "vowel"


def visemes_of(phones: Iterable[str]) -> List[str]:
    seen = []
    for p in phones:
        g = viseme_of(p)
        if g not in seen:
            seen.append(g)
    return seen
