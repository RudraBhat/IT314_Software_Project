"""Sanitised, explicitly simulated social-signal replay adapter."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.ingest.base import Adapter

logger = logging.getLogger("drch.ingest.signals")
MAX_SIGNAL_CHARS = 2_000
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SPACE_RE = re.compile(r"\s+")
# A well-formed tag: a tag name with no spaces, then only name=value attributes; or a comment, CDATA,
# doctype or processing instruction. Text such as "level <Low at gate A, high at gate B> rising" or
# "a<b and c>d" is not a tag and is kept. Every part is bounded and the attribute group has one fixed
# shape, so matching stays linear on long input.
_TAG_ATTR = r"""\s+[A-Za-z_:@][\w:.\-]{0,40}\s*=\s*(?:"[^"<>]{0,300}"|'[^'<>]{0,300}'|[^\s<>]{1,300})"""
TAG_RE = re.compile(
    r"<(?:/?[A-Za-z][A-Za-z0-9:\-]{0,30}(?:" + _TAG_ATTR + r"){0,20}\s*/?"
    r"|!--[\s\S]{0,2000}?--|!\[CDATA\[[\s\S]{0,2000}?\]\]|![A-Za-z][^<>]{0,200}|\?[^<>]{0,200}\?)>",
    re.IGNORECASE,
)
_KEEP_FORMAT_CHARS = frozenset({"\u200c", "\u200d"})  # ZWNJ, ZWJ


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def _drop_invisible(text: str) -> str:
    """Remove zero-width, bidi-override and other invisible format characters (Unicode Cf).

    ZWNJ/ZWJ are kept because Hindi and Gujarati spelling uses them. Removing the rest stops
    a post from hiding words from the dispatcher or splitting a word to dodge a filter.
    """
    return "".join(ch for ch in text if ch in _KEEP_FORMAT_CHARS or unicodedata.category(ch) != "Cf")


def _escape_non_tags(text: str) -> str:
    """Escape every "<" that does not start a well-formed tag, so the HTML parser keeps it as text."""
    out: list[str] = []
    position = 0
    for match in TAG_RE.finditer(text):
        out.append(text[position:match.start()].replace("<", "&lt;"))
        out.append(match.group())
        position = match.end()
    out.append(text[position:].replace("<", "&lt;"))
    return "".join(out)


def sanitise_signal_text(value: str) -> str:
    """Strip markup, links, controls and invisible characters, then bound text before triage or storage.

    Invisible characters are removed first (and again after entities are decoded), so a zero-width space
    cannot split "</report>", "https://" or "www." past the filters and reassemble them afterwards.
    """
    text = _drop_invisible(value or "")
    parser = _TextExtractor()
    parser.feed(_escape_non_tags(text))
    parser.close()
    text = _drop_invisible(" ".join(parser.parts))  # entities such as &#8203; decode only here
    # The parser decodes entities, so "&lt;/report&gt;" comes out as a literal tag; remove those too.
    # Repeat until nothing changes, so a tag rebuilt by removing an inner one is also removed.
    for _ in range(5):
        stripped = TAG_RE.sub(" ", text)
        if stripped == text:
            break
        text = stripped
    text = URL_RE.sub(" ", text)
    text = CONTROL_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()[:MAX_SIGNAL_CHARS]


def detect_language(value: str, declared_language: str | None = None, *, latin_fallback: str = "en") -> str:
    """Detect Indic scripts and use a source hint to distinguish Romanised Hindi/Gujarati."""
    counts = {"gu": 0, "hi": 0}
    for char in value:
        code = ord(char)
        if 0x0A80 <= code <= 0x0AFF:
            counts["gu"] += 1
        elif 0x0900 <= code <= 0x097F:
            counts["hi"] += 1
    if counts["gu"] or counts["hi"]:
        return max(counts, key=counts.get)
    base = (declared_language or "").strip().replace("_", "-").split("-", 1)[0].lower()
    if base in {"gu", "hi"}:
        return f"{base}-Latn"
    if base == "en":
        return "en"
    return latin_fallback if any(ch.isalpha() for ch in value) else "und"


# Words that make a live text worth a dispatcher's look, limited to the supported scenarios
# (cyclone, industrial fire, urban flooding). Matching is a cheap pre-filter only; the advisory
# triage label and the human review decide what the text is about.
HAZARD_TERMS = (
    "flood", "waterlog", "inundat", "heavy rain", "cloudburst", "cyclone", "storm surge", "landfall",
    "fire", "blaze", "blast", "explosion", "gas leak", "chemical leak", "toxic",
    "પૂર", "વરસાદ", "વાવાઝોડ", "ચક્રવાત", "આગ", "વિસ્ફોટ", "ગેસ લીક",
    "बाढ़", "बारिश", "चक्रवात", "तूफान", "आग", "विस्फोट", "गैस रिसाव",
)
ROMAN_HAZARD_TERMS = (
    "baadh", "baad", "baarish", "barish", "toofan", "tufan", "chakravat",
    "pur", "varsad", "varasad", "vavazodu", "vavajodu", "aag", "aag lagi",
    "visfot", "visphot", "dhamaka", "dhamako", "gas risav",
)
_ROMAN_HAZARD_RE = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(re.escape(term) for term in ROMAN_HAZARD_TERMS) + r")(?![a-z0-9])",
    re.IGNORECASE,
)

# Place names (lower-case) mapped to the Gujarat district whose centroid stands in for the
# location. Bigger towns and industrial estates are mapped to their district.
_PLACE_ALIASES = {
    "baroda": "Vadodara", "kachchh": "Kutch", "bhuj": "Kutch", "gandhidham": "Kutch", "mundra": "Kutch",
    "kandla": "Kutch", "dahej": "Bharuch", "ankleshwar": "Bharuch", "vapi": "Valsad", "hazira": "Surat",
    "dwarka": "Devbhoomi Dwarka", "somnath": "Gir Somnath", "veraval": "Gir Somnath",
    "godhra": "Panchmahal", "halol": "Panchmahal", "nadiad": "Kheda", "palanpur": "Banaskantha",
    "himmatnagar": "Sabarkantha", "modasa": "Aravalli", "pipavav": "Amreli", "sanand": "Ahmedabad",
    "અમદાવાદ": "Ahmedabad", "સુરત": "Surat", "વડોદરા": "Vadodara", "રાજકોટ": "Rajkot", "કચ્છ": "Kutch",
    "ભુજ": "Kutch", "જામનગર": "Jamnagar", "ભાવનગર": "Bhavnagar", "જૂનાગઢ": "Junagadh", "ભરૂચ": "Bharuch",
    "વલસાડ": "Valsad", "નવસારી": "Navsari", "પોરબંદર": "Porbandar", "ગાંધીનગર": "Gandhinagar",
    "मोरबी": "Morbi", "अहमदाबाद": "Ahmedabad", "सूरत": "Surat", "वडोदरा": "Vadodara", "राजकोट": "Rajkot",
    "कच्छ": "Kutch", "जामनगर": "Jamnagar", "भरूच": "Bharuch",
}
_STATE_TERMS = ("gujarat", "saurashtra", "ગુજરાત", "સૌરાષ્ટ્ર", "गुजरात", "सौराष्ट्र")


# Short Indic words that also begin unrelated words (आगमन "arrival", આગામી "upcoming",
# પૂરતું "enough"). They match only as a whole word or with a Gujarati case ending.
_STRICT_INDIC_TERMS = {"આગ", "પૂર", "आग", "बाढ़"}
_GUJARATI_ENDINGS = ("", "માં", "થી", "નો", "ની", "નું", "ના", "ને", "ે", "ો")
_TOKEN_RE = re.compile(r"[^\s.,:;!?\"'()\[\]{}|/\\\-–—…]+")


def mentions_hazard(text: str) -> bool:
    lowered = (text or "").lower()
    if _ROMAN_HAZARD_RE.search(lowered):
        return True
    loose = [term for term in HAZARD_TERMS if term not in _STRICT_INDIC_TERMS]
    if any(term in lowered for term in loose):
        return True
    tokens = _TOKEN_RE.findall(lowered)
    return any(
        token.startswith(term) and token[len(term):] in _GUJARATI_ENDINGS
        for token in tokens for term in _STRICT_INDIC_TERMS
    )


def _names_in(text: str, names: dict[str, str]) -> set[str]:
    found = set()
    for name, district in names.items():
        if name.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", text):
                found.add(district)
        elif name in text:  # Gujarati/Hindi case endings attach to the name, so match a substring
            found.add(district)
    return found


def locate_gujarat_text(text: str) -> dict[str, Any] | None:
    """Return a district-level location when the text names exactly one Gujarat district.

    The coordinates are the district centroid, never a precise point, and the result says so.
    Returns None when the text does not mention Gujarat at all. A text that names Gujarat but no
    single district gets no coordinates, so a dispatcher must add the location before promotion.
    """
    from app.geo import district_centroids

    centroids = district_centroids()
    lowered = (text or "").lower()
    found = _names_in(lowered, {name.lower(): name for name in centroids} | _PLACE_ALIASES)
    if not found and not any(term in lowered for term in _STATE_TERMS):
        return None
    if len(found) == 1:
        district = found.pop()
        lat, lon = centroids[district]
        return {"location_text": f"{district} district (approximate, named in text)",
                "latitude": lat, "longitude": lon, "district": district}
    return {"location_text": "Gujarat (district not identified)", "latitude": None, "longitude": None,
            "district": None}


def stable_uid(*parts: str) -> str:
    """Hash an external identifier so it never stores an account id or a long URL."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:40]


class ReplaySignalAdapter(Adapter):
    """Read team-authored replay items; never fetches or stores live user posts."""

    name = "REPLAY"
    kind = "signal"

    def __init__(self, replay_file: str | None = None) -> None:
        configured = (replay_file or get_settings().social_replay_file).strip()
        self.path = Path(configured) if configured else Path(__file__).resolve().parents[3] / "app" / "data" / "social_replay.jsonl"

    def fetch(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            logger.warning("Signal replay dataset not found: %s", self.path)
            return []
        items: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as stream:
            for row_num, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid replay JSON on line {row_num}") from exc
                text = sanitise_signal_text(str(row.get("text", "")))
                if not text:
                    continue
                uid = str(row.get("id") or hashlib.sha256(text.encode()).hexdigest()[:32])
                lat, lon = row.get("latitude"), row.get("longitude")
                items.append({
                    "source": self.name,
                    "source_uid": uid,
                    "content_text": text,
                    "language": detect_language(text),
                    "location_text": str(row.get("location") or "")[:200] or None,
                    "latitude": float(lat) if lat is not None else None,
                    "longitude": float(lon) if lon is not None else None,
                    "location_precision": "EXACT" if lat is not None and lon is not None else "NONE",
                    "is_simulated": True,
                    "raw_payload": {
                        "dataset": "social_replay",
                        "synthetic": True,
                        "location_precision": "exact" if lat is not None and lon is not None else "none",
                    },
                })
        return items
