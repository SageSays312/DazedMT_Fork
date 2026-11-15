"""Source-language registry for DazedTL.

DazedTL was originally written for Japanese → X translation. The active
source language is read from the ``source_language`` environment variable
(default: "Japanese"). This registry drives:

- the regex used by modules to decide "is this string in the source language?"
- the residue regex used after translation to detect leftover source chars
- prompt file selection (see util/skills/system.py)

The language-agnostic extraction itself is done structurally by each
engine module (walking event codes), not by these regexes. They are only
a secondary filter.
"""
from __future__ import annotations

import os
import re

# Regex that matches at least one character of the given source language.
# Used as a filter in ``_has_source_text()`` and as an inline character
# class in engine-specific plugin patterns (namePop, LB, dn, ...).
LANGREGEX_BY_LANG: dict[str, str] = {
    # Original DazedTL behaviour. Kept byte-identical to the previous
    # hardcoded value so current Japanese translations are unchanged.
    "Japanese": (
        r"[\u3000\u3002-\u3009\u300C-\u303F\u3040-\u309A\u309C-\u30FA"
        r"\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
        r"\uFF61-\uFF9F]+"
    ),
    # Chinese (Simplified + Traditional + Extension B).
    "Chinese": (
        r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
        r"\U00020000-\U0002A6DF]+"
    ),
    # Korean (Hangul syllables + Jamo + compatibility Jamo).
    "Korean": r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]+",
    # English. Matches almost any ASCII letter run, so the "is this the
    # source language?" filter is effectively a no-op for English. That is
    # intentional: the structural extractor already picks the right fields.
    "English": r"[A-Za-z]+",
    "Russian": r"[А-Яа-яЁё]+",
    "Spanish": r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+",
    "Portuguese": r"[A-Za-zÁÂÃÀÇÉÊÍÓÔÕÚáâãàçéêíóôõú]+",
    "French": r"[A-Za-zÀÂÇÉÈÊËÎÏÔÙÛÜàâçéèêëîïôùûü]+",
    "German": r"[A-Za-zÄÖÜßäöü]+",
    "Italian": r"[A-Za-zÀÈÉÌÍÎÒÓÙÚàèéìíîòóùú]+",
}

# Regex that matches leftover source-language characters in a translated
# string. Used by the post-translation validator in util/translation.py.
# ``None`` means "no residue check applies for this source language".
#
# For Japanese source the residue is kana (kanji is legitimately shared
# with Chinese, so kanji alone is not proof of untranslated text). For
# alphabetic source languages, residue cannot be distinguished from
# legitimate output, so no check is performed.
RESIDUE_REGEX_BY_LANG: dict[str, str | None] = {
    "Japanese": r"[ぁ-ゖァ-ヺー\uFF66-\uFF9F]",
    "Chinese": None,
    "Korean": r"[\uAC00-\uD7AF]",
    "English": None,
    "Russian": None,
    "Spanish": None,
    "Portuguese": None,
    "French": None,
    "German": None,
    "Italian": None,
}

DEFAULT_SOURCE_LANGUAGE = "Japanese"

# Game/UI abbreviations that appear in labels like "x3 DEF", "ATK +5",
# "AP:20". These are not natural language and must not be flagged as
# untranslated passthrough. Lowercase for case-insensitive lookup.
_GAME_ABBREVIATIONS = frozenset({
    "ap", "hp", "mp", "mhp", "mmp", "atk", "def", "spd", "exp",
    "se", "bgm", "bgs", "me", "wasd", "fps", "crit", "cd", "emp",
    "npc", "ui", "hud", "rpg", "dps", "aoe",
    "enter", "esc", "tab", "shift", "ctrl", "alt",
})


def get_source_language() -> str:
    """Return the configured source language, defaulting to Japanese."""
    value = (os.getenv("source_language") or "").strip()
    return value or DEFAULT_SOURCE_LANGUAGE


def get_lang_regex(language: str | None = None) -> str:
    """Return the source-language regex for the given (or configured) language."""
    lang = language or get_source_language()
    return LANGREGEX_BY_LANG.get(lang, LANGREGEX_BY_LANG[DEFAULT_SOURCE_LANGUAGE])


def get_residue_regex(language: str | None = None) -> str | None:
    """Return the residue-check regex, or None if no check applies."""
    lang = language or get_source_language()
    return RESIDUE_REGEX_BY_LANG.get(lang)


def is_known_language(language: str) -> bool:
    """Return True if the language has an entry in the registry."""
    return language in LANGREGEX_BY_LANG


# Script that MUST appear in a translated string for the given TARGET language.
# Used to detect untranslated passthrough (e.g., English source left as English
# when translating to Russian). ``None`` means "the target uses the same script
# as common source languages, so script-based detection cannot apply".
TARGET_SCRIPT_BY_LANG: dict[str, str | None] = {
    "Japanese": r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF]",
    "Chinese":  r"[\u3400-\u4DBF\u4E00-\u9FFF]",
    "Korean":   r"[\uAC00-\uD7AF\u1100-\u11FF]",
    "Russian":  r"[\u0400-\u04FF]",
    "Greek":    r"[\u0370-\u03FF]",
    "Arabic":   r"[\u0600-\u06FF]",
    "Hebrew":   r"[\u0590-\u05FF]",
    "Thai":     r"[\u0E00-\u0E7F]",
    "Hindi":    r"[\u0900-\u097F]",
    # Latin-script targets: cannot be distinguished from English source by script.
    "English":    None,
    "Spanish":    None,
    "French":     None,
    "German":     None,
    "Italian":    None,
    "Portuguese": None,
}


def get_target_script_regex(language: str | None = None) -> str | None:
    """Return the target-script presence regex, or None if not applicable."""
    lang = language or (os.getenv("language") or "English").strip() or "English"
    return TARGET_SCRIPT_BY_LANG.get(lang)


def _looks_like_code_or_marker(text: str) -> bool:
    """Return True for strings that are clearly not natural language.

    Covers:
      - Game markers: ###XXX (any line starting with ###)
      - Angle-bracket tags: <thinking Caly>, <speaker>, <Seed Bed ending>
      - RPG Maker editor previews: ◆Text：None, Window, Bottom
      - Pure control codes + punctuation: \\m[2]..., \\v[281]
      - Short all-caps identifiers: MAP034, UR-556, LAF
      - Any Latin-only string with no lowercase, no spaces, no sentence punct
    """
    s = (text or "").strip()
    if not s:
        return True
    s = re.sub(r"__PROTECTED_\d+__", "", s).strip()
    if not s:
        return True
    if len(s) < 4:
        return True
    # Game markers: any line starting with ###
    if s.startswith("###"):
        return True
    # Single angle-bracket tag with no nesting: <thinking Caly>, <speaker>
    if re.fullmatch(r"<[^<>]{1,80}>", s):
        return True
    # RPG Maker editor previews: ◆Text：..., ◆Plugin Command：...
    if s.startswith("◆"):
        return True
    # Strip RPG Maker control codes (\\m[2], \\v[281], \\i[100], \\c[4]) and
    # backslash escapes, then check what letters remain.
    stripped_codes = re.sub(r"\\+[A-Za-z]+\[[^\]]*\]", "", s)
    stripped_codes = re.sub(r"\\+[A-Za-z]+", "", stripped_codes)
    stripped_codes = stripped_codes.replace("\\", "").strip()
    # If after stripping control codes there are no letters at all, it is
    # pure punctuation / digits / control codes.
    if not re.search(r"[A-Za-z\u00C0-\u024F\u0400-\u04FF\u3040-\u30FF\u4E00-\u9FFF]", stripped_codes):
        return True

    # Non-Latin alphabetic content is natural language.
    if any(c.isalpha() and ord(c) > 127 for c in stripped_codes):
        return False
    has_lower = any(c.islower() for c in stripped_codes)
    has_digit = any(c.isdigit() for c in stripped_codes)

    _ALPHA_TOKENS = re.findall(r"[A-Za-z]+", stripped_codes)
    if _ALPHA_TOKENS and all(
            len(w) == 1 or w.casefold() in _GAME_ABBREVIATIONS
            for w in _ALPHA_TOKENS
    ):
        return True

    # Short all-caps identifier, no spaces: MAP034, UR-556, LAF
    # Short identifier vs real word. ENTER / LAF / MAP034 (all-caps) and
    # UR-556 / v8.93 (with digits) are identifiers. Turret / Shield / Mine
    # (proper-cased English nouns) are real words that need translation.
    if len(stripped_codes) <= 12 and " " not in stripped_codes:
        if not has_lower:
            return True  # all-caps identifier
        if has_digit:
            return True  # digit-containing identifier
        if stripped_codes[0].isupper() and stripped_codes[1:].islower():
            return False  # proper-cased English word
        return True  # other short identifier
    has_lower = any(c.islower() for c in stripped_codes)
    has_punct = any(c in ",.!?;:«»\"'()" for c in stripped_codes)
    if not has_lower and not has_punct and " " not in stripped_codes:
        return True
    return False


# Source languages whose extraction LANGREGEX is a broad Latin-letter class
# (``[A-Za-z...]+``) and therefore false-positives on short identifiers,
# codes, and labels like ``x12`` or ``UR-556``. For these sources the
# validator must use the target-script + residue-regex pair instead of
# matching raw LANGREGEX against translated text.
BROAD_REGEX_SOURCES: frozenset[str] = frozenset({
    "English", "Spanish", "French", "German", "Italian", "Portuguese",
})


def source_uses_broad_regex(language: str | None = None) -> bool:
    """True when this source language's LANGREGEX is the broad Latin class."""
    lang = language or get_source_language()
    return lang in BROAD_REGEX_SOURCES