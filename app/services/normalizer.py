from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.models import NormalizedProduct, RawListing

VARIANT_PHRASES = (
    "magic masala", "cream and onion", "cream onion", "sugar free", "salted", "unsalted",
    "regular", "zero", "diet", "tomato", "cheese", "garlic", "chicken", "veg", "mango", "orange",
)
STOPWORDS = {"with", "made", "quality", "instant", "pack", "family", "of"}


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("’", "'").replace("×", "x")
    value = re.sub(r"[^\w.×x]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


@dataclass(frozen=True)
class ParsedQuantity:
    measure_kind: str = "unknown"
    item_amount_base: float | None = None
    base_unit: str | None = None
    pack_count: int = 1
    total_amount_base: float | None = None


_UNITS = r"(?P<unit>kg|kgs|kilograms?|g|gm|gms|grams?|ml|l|litres?|liters?|pcs?|pieces?)"
_NUMBER = r"(?P<amount>\d+(?:\.\d+)?)"


def _base(amount: float, unit: str) -> tuple[str, float, str]:
    unit = unit.casefold()
    if unit in {"kg", "kgs", "kilogram", "kilograms", "g", "gm", "gms", "gram", "grams"}:
        return "mass", amount * (1000 if unit.startswith("k") else 1), "g"
    if unit in {"l", "litre", "litres", "liter", "liters", "ml"}:
        return "volume", amount * (1000 if unit != "ml" else 1), "ml"
    return "count", amount, "pcs"


def parse_quantity(value: str | None) -> ParsedQuantity:
    if not value:
        return ParsedQuantity()
    text = normalize_text(value)
    # 4 x 70 g, 4×70g
    match = re.search(rf"(?P<count>\d+)\s*[x×]\s*{_NUMBER}\s*{_UNITS}", text)
    if not match:
        # 70 g x 4
        match = re.search(rf"{_NUMBER}\s*{_UNITS}\s*[x×]\s*(?P<count>\d+)", text)
    if match:
        count = int(match.group("count"))
        kind, amount, unit = _base(float(match.group("amount")), match.group("unit"))
        return ParsedQuantity(kind, amount, unit, count, amount * count)
    match = re.search(r"\bpack\s+of\s+(\d+)\b", text)
    if match:
        count = int(match.group(1))
        return ParsedQuantity("count", 1, "pcs", count, float(count))
    match = re.search(rf"{_NUMBER}\s*{_UNITS}", text)
    if match:
        kind, amount, unit = _base(float(match.group("amount")), match.group("unit"))
        return ParsedQuantity(kind, amount, unit, 1, amount)
    return ParsedQuantity()


def _variant_tokens(raw: RawListing, normalized_title: str) -> set[str]:
    source = " ".join([normalized_title, *raw.attributes.values()])
    source = normalize_text(source)
    found: set[str] = set()
    for phrase in VARIANT_PHRASES:
        normalized_phrase = normalize_text(phrase)
        if re.search(rf"\b{re.escape(normalized_phrase)}\b", source):
            found.add(normalized_phrase)
    return found


from rapidfuzz import fuzz

KNOWN_BRANDS = {
    "amul", "maggi", "coca cola", "coke", "lays", "lay", "mother dairy",
    "country delight", "britannia", "bingo", "crax", "wai wai", "nestle",
    "act ii", "pepsi", "haldiram", "too yumm", "cadbury", "oreo", "parle",
    "nutralite", "milky mist", "frubon", "b natural", "paper boat", "snackible",
}

QUERY_SYNONYMS: dict[str, list[str]] = {
    "coca cola": ["coca cola", "coke", "coca-cola"],
    "coke": ["coca cola", "coke", "coca-cola"],
    "lays": ["lays", "lay"],
}


def is_query_relevant(query: str, title: str) -> bool:
    """Lightweight filter to drop unrelated sponsored ads while retaining relevant ones."""
    q_norm = normalize_text(query)
    t_norm = normalize_text(title)
    t_tokens = set(t_norm.split())

    for canon, aliases in QUERY_SYNONYMS.items():
        if q_norm == canon or canon in q_norm:
            if any(alias in t_norm or set(alias.split()).issubset(t_tokens) for alias in aliases):
                return True

    q_tokens = [tok for tok in q_norm.split() if tok not in STOPWORDS and len(tok) > 1]
    if not q_tokens:
        return True

    if len(q_tokens) == 1:
        q_tok = q_tokens[0]
        return any(q_tok in word or word in q_tok or fuzz.ratio(q_tok, word) >= 80 for word in t_tokens)

    matched = [tok for tok in q_tokens if any(tok in word or fuzz.ratio(tok, word) >= 80 for word in t_tokens)]
    if len(matched) == len(q_tokens):
        return True

    first_tok = q_tokens[0]
    if first_tok in t_tokens or any(fuzz.ratio(first_tok, word) >= 85 for word in t_tokens):
        return fuzz.token_set_ratio(q_norm, t_norm) >= 50

    return False


def _brand_hint(raw: RawListing, tokens: list[str]) -> str | None:
    for key, value in raw.attributes.items():
        if key.casefold() == "brand" and value.strip():
            return normalize_text(value)
    title_norm = normalize_text(raw.title)
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(brand)}\b", title_norm):
            return brand
    return None


def normalize_listing(raw: RawListing) -> NormalizedProduct:
    normalized_title = normalize_text(raw.title)
    parsed = parse_quantity(raw.size_text or raw.title or raw.raw_text)
    # Remove standalone numeric/unit details from similarity, but keep all meaningful variants.
    title_for_tokens = re.sub(rf"\b\d+(?:\.\d+)?\s*(?:{_UNITS}|x)\b", " ", normalized_title)
    tokens = [token for token in title_for_tokens.split() if token not in STOPWORDS and not token.isdigit()]
    return NormalizedProduct(
        raw=raw,
        normalized_title=" ".join(tokens),
        title_tokens=tokens,
        brand_hint=_brand_hint(raw, tokens),
        variant_tokens=_variant_tokens(raw, normalized_title),
        measure_kind=parsed.measure_kind,
        item_amount_base=parsed.item_amount_base,
        base_unit=parsed.base_unit,
        pack_count=parsed.pack_count,
        total_amount_base=parsed.total_amount_base,
    )
