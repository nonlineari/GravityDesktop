"""ARPAbet ↔ IPA (2020 pulmonic subset used in prompts)."""

from __future__ import annotations

import re
from typing import Iterable, List

# CMU ARPAbet (no stress) → IPA. Reverse is unique on these values.
ARPABET_IPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "EH": "ɛ", "ER": "ɝ",
    "EY": "eɪ", "F": "f", "G": "ɡ", "HH": "h", "IH": "ɪ", "IY": "i",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ",
    "OW": "oʊ", "OY": "ɔɪ", "P": "p", "R": "r", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "UH": "ʊ", "UW": "u", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ", "AX": "ə",
}
IPA_ARPABET = {v: k for k, v in ARPABET_IPA.items()}

_STRESS = re.compile(r"[0-2]$")


def strip_stress(phone: str) -> str:
    p = phone.strip().upper()
    return _STRESS.sub("", p)


def to_ipa(phone: str) -> str:
    key = strip_stress(phone)
    if phone in ARPABET_IPA:
        return ARPABET_IPA[phone]
    if key in ARPABET_IPA:
        return ARPABET_IPA[key]
    # already IPA
    if phone in IPA_ARPABET:
        return phone
    return phone


def to_arpabet(ipa: str) -> str:
    if ipa in IPA_ARPABET:
        return IPA_ARPABET[ipa]
    up = ipa.upper()
    if up in ARPABET_IPA:
        return up
    return ipa


def phones_to_ipa(phones: Iterable[str]) -> List[str]:
    return [to_ipa(p) for p in phones if str(p).strip()]


def parse_ipa_token(token: str) -> str:
    """Accept θ, /θ/, ipa:θ, ipa:/θ/."""
    t = token.strip()
    t = re.sub(r"^[Ii][Pp][Aa]:", "", t)
    t = t.strip("/")
    return t
