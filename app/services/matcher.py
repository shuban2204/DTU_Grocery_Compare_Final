from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from app.models import NormalizedProduct


@dataclass(frozen=True)
class PairMatch:
    relationship: str
    score: float
    blinkit: NormalizedProduct
    instamart: NormalizedProduct
    reasons: list[str]


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(abs(a), abs(b), 1.0) * 0.01


def _variant_conflict(a: NormalizedProduct, b: NormalizedProduct) -> bool:
    left, right = a.variant_tokens, b.variant_tokens
    if not left and not right:
        return False

    # Salted vs Unsalted: only conflicts if both are explicitly opposite
    if ("salted" in left and "unsalted" in right) or ("unsalted" in left and "salted" in right):
        return True

    # Veg vs Chicken
    if ("veg" in left and "chicken" in right) or ("chicken" in left and "veg" in right):
        return True

    # Diet / Zero vs Regular:
    diet_markers = {"zero", "diet", "sugar free"}
    has_diet_a = bool(left.intersection(diet_markers))
    has_diet_b = bool(right.intersection(diet_markers))
    if has_diet_a != has_diet_b:
        return True

    # Mutually exclusive flavour phrases
    flavour_markers = {
        "magic masala", "cream and onion", "cream onion", "tomato", "cheese", "garlic",
        "orange", "mango",
    }
    flavours_a = left.intersection(flavour_markers)
    flavours_b = right.intersection(flavour_markers)
    if flavours_a and flavours_b and not flavours_a.intersection(flavours_b):
        return True

    return False


def _brand_conflict(a: NormalizedProduct, b: NormalizedProduct) -> bool:
    if a.brand_hint and b.brand_hint:
        brand_a = "coca cola" if a.brand_hint in {"coke", "coca-cola"} else ("lays" if a.brand_hint == "lay" else a.brand_hint)
        brand_b = "coca cola" if b.brand_hint in {"coke", "coca-cola"} else ("lays" if b.brand_hint == "lay" else b.brand_hint)
        return brand_a != brand_b
    return False


def classify(a: NormalizedProduct, b: NormalizedProduct) -> tuple[str | None, float, list[str]]:
    score = fuzz.token_set_ratio(a.normalized_title, b.normalized_title)
    if _variant_conflict(a, b) or _brand_conflict(a, b):
        return None, score, ["variant or brand conflict"]
    compatible_measure = a.measure_kind == "unknown" or b.measure_kind == "unknown" or a.measure_kind == b.measure_kind
    if not compatible_measure:
        return None, score, ["incompatible measurement"]

    # Exact match REQUIRES sizes to be known on both sides, equal amounts, same base unit, same pack count!
    sizes_known = a.item_amount_base is not None and b.item_amount_base is not None
    same_item = sizes_known and a.base_unit == b.base_unit and _close(a.item_amount_base, b.item_amount_base)
    same_pack = a.pack_count == b.pack_count

    # If one product specifies a flavour/variant and the other does not, it cannot be exact same SKU
    has_variant_mismatch = bool(a.variant_tokens ^ b.variant_tokens)

    if score >= 84 and sizes_known and same_item and same_pack and not has_variant_mismatch:
        return "exact", score, ["strong title similarity", "same parsed size and pack structure"]

    # Comparable: shared product family and compatible measurement type.
    # Covers different sizes/packaging, or unknown size on one or both items.
    if score >= 74 and compatible_measure:
        reasons = ["same product family"]
        if not sizes_known:
            reasons.append("one or both sizes unknown; treated as comparable")
        else:
            reasons.append("different size or pack structure")
        return "comparable", score, reasons

    return None, score, ["insufficient conservative match confidence"]


def pair_products(blinkit: list[NormalizedProduct], instamart: list[NormalizedProduct]) -> tuple[list[PairMatch], list[NormalizedProduct], list[NormalizedProduct]]:
    exact: list[PairMatch] = []
    comparable: list[PairMatch] = []
    for b_index, b in enumerate(blinkit):
        for i_index, i in enumerate(instamart):
            relation, score, reasons = classify(b, i)
            if relation:
                match = PairMatch(relation, score, b, i, reasons)
                (exact if relation == "exact" else comparable).append(match)
    used_b: set[int] = set()
    used_i: set[int] = set()
    accepted: list[PairMatch] = []
    # Object identity is stable within this matching call and enforces one-to-one greedy selection.
    b_ids = {id(item): index for index, item in enumerate(blinkit)}
    i_ids = {id(item): index for index, item in enumerate(instamart)}
    for candidate in sorted(exact, key=lambda pair: pair.score, reverse=True) + sorted(comparable, key=lambda pair: pair.score, reverse=True):
        b_index, i_index = b_ids[id(candidate.blinkit)], i_ids[id(candidate.instamart)]
        if b_index not in used_b and i_index not in used_i:
            accepted.append(candidate)
            used_b.add(b_index)
            used_i.add(i_index)
    return accepted, [item for index, item in enumerate(blinkit) if index not in used_b], [item for index, item in enumerate(instamart) if index not in used_i]
