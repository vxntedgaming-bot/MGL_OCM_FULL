"""FC26 recognised / display-name mapping.

The official FC26 export has two name columns:

- ``short_name`` — the recognised FUT-style name (``M. Salah``, ``K. Mbappé``,
  ``Rodri``, ``Bruno Fernandes``, ``Vini Jr.``).
- ``long_name`` — the legal name, often with extra surnames and a non-Latin
  script glued on (``Mohamed Salah Hamed Ghalyمحمد صلاح``).

MGL previously stored ``long_name`` as ``Player.name``. Card rendering then
took the last token of names with 3+ parts, so Salah displayed as Ghaly,
Mbappé as Lottin, and Hakimi as Mouh.

The recognised display name is derived from **both** columns, never from a
hardcoded player list:

- If ``short_name`` is already a full known name (no leading initial), use it.
- If ``short_name`` is ``X. Surname``, take the first given name from the
  Latin ``long_name`` plus the FC26 surname (matched accent-insensitively
  inside ``long_name`` so accents like Mbappé are preserved).
"""

from __future__ import annotations

import re
import unicodedata


INITIAL_SHORT_NAME = re.compile(
    r"^((?:[A-Za-zÀ-ÖØ-öø-ÿ]\.\s+)+)(.+)$",
)
DOUBLE_VOWEL = re.compile(r"([aeiou])\1+")


def fold_search_text(value: str) -> str:
    """Casefold and strip combining marks so Mbappe matches Mbappé."""
    normalized = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    folded = stripped.replace("æ", "ae").replace("Æ", "ae").replace("ø", "o").replace("Ø", "o")
    return folded.casefold()


def search_haystack(value: str) -> str:
    """Folded text with doubled vowels collapsed (Haaland ↔ Håland)."""
    return DOUBLE_VOWEL.sub(r"\1", fold_search_text(value))


def latin_name(value: str) -> str:
    """Keep the Latin spelling and drop a glued-on non-Latin script suffix."""
    chars = []
    for char in value or "":
        if ord(char) > 900 and not char.isspace() and char not in "-'.":
            break
        chars.append(char)
    return "".join(chars).strip(" -")


def _tokens(value: str) -> list[str]:
    return [part for part in (value or "").split() if part]


def _strip_token(value: str) -> str:
    return (value or "").strip(".,")


def _is_initial_short_name(short_name: str) -> bool:
    return bool(INITIAL_SHORT_NAME.match((short_name or "").strip()))


def _known_surname(short_name: str) -> str:
    match = INITIAL_SHORT_NAME.match((short_name or "").strip())
    if match:
        return match.group(2).strip()
    return (short_name or "").strip()


def _token_matches(long_token: str, known_part: str) -> str | None:
    """Return the spelling to keep when a long_name token matches a short_name part."""
    long_token = (long_token or "").strip()
    known_part = (known_part or "").strip()
    long_clean = _strip_token(long_token)
    known_clean = _strip_token(known_part)
    long_fold = fold_search_text(long_clean)
    known_fold = fold_search_text(known_clean)
    if long_fold == known_fold:
        return long_token
    long_head = long_clean.split("-", 1)[0]
    if fold_search_text(long_head) == known_fold:
        return long_head
    if search_haystack(long_clean) == search_haystack(known_clean):
        return known_part
    if known_part.endswith(".") and len(known_fold) >= 3 and long_fold.startswith(known_fold):
        return long_token
    return None


def _matched_surname(long_tokens: list[str], known_parts: list[str]) -> list[str] | None:
    if not known_parts or not long_tokens:
        return None
    width = len(known_parts)
    for index in range(0, len(long_tokens) - width + 1):
        spelling = []
        for offset, part in enumerate(known_parts):
            matched = _token_matches(long_tokens[index + offset], part)
            if matched is None:
                break
            spelling.append(matched)
        else:
            return spelling
    return None


def fc26_display_name(short_name: str | None, long_name: str | None) -> str:
    """Return the recognised FC26 display name for one player row."""
    short_name = (short_name or "").strip()
    latin_long = latin_name(long_name or "")

    if not short_name:
        return latin_long or (long_name or "").strip()

    if not _is_initial_short_name(short_name):
        return short_name

    known = _known_surname(short_name)
    known_parts = _tokens(known)
    long_tokens = _tokens(latin_long)
    given = long_tokens[0] if long_tokens else ""
    surname_parts = _matched_surname(long_tokens, known_parts)
    if surname_parts is None:
        surname = known
    else:
        surname = " ".join(surname_parts)

    if given and search_haystack(given) != search_haystack(_tokens(surname)[0] if surname else ""):
        return f"{given} {surname}".strip()
    return surname or short_name


def display_name_from_row(row: dict) -> str:
    return fc26_display_name(row.get("short_name"), row.get("long_name"))


def name_matches_query(name: str, query: str) -> bool:
    """True when query is a substring of name, ignoring case and accents."""
    folded_query = fold_search_text(query)
    if not folded_query:
        return False
    folded_name = fold_search_text(name)
    if folded_query in folded_name:
        return True
    collapsed_query = search_haystack(query)
    collapsed_name = search_haystack(name)
    return bool(collapsed_query) and collapsed_query in collapsed_name
