from datetime import datetime, timezone
from decimal import Decimal

from app.models import RawListing
from app.services.matcher import classify, pair_products
from app.services.normalizer import normalize_listing


def item(platform: str, title: str, size: str) -> object:
    return normalize_listing(RawListing(platform=platform, title=title, size_text=size, price=Decimal("20"), raw_text=f"{title} {size}", fetched_at=datetime.now(timezone.utc)))


def test_amul_same_sku_is_exact():
    relation, _, _ = classify(item("blinkit", "Amul Pasteurised Salted Butter", "500 g"), item("instamart", "Amul Salted Butter", "0.5 kg"))
    assert relation == "exact"


def test_coca_cola_zero_is_not_paired_as_exact():
    relation, _, _ = classify(item("blinkit", "Coca-Cola", "750 ml"), item("instamart", "Coca-Cola Zero", "750 ml"))
    assert relation is None


def test_different_brands_are_not_exact_matches():
    relation, _, _ = classify(item("blinkit", "Amul Salted Butter", "500 g"), item("instamart", "Mother Dairy Salted Butter", "500 g"))
    assert relation is None


def test_different_flavours_are_not_paired():
    relation, _, _ = classify(item("blinkit", "Lay's Magic Masala", "52 g"), item("instamart", "Lay's Cream and Onion", "52 g"))
    assert relation is None


def test_lays_different_size_is_comparable():
    relation, _, _ = classify(item("blinkit", "Lay's Magic Masala", "52 g"), item("instamart", "Lay's Magic Masala", "48 g"))
    assert relation == "comparable"


def test_maggi_multipack_and_family_pack_are_comparable():
    relation, _, _ = classify(item("blinkit", "Maggi Masala", "4 x 70 g"), item("instamart", "Maggi Masala Family Pack", "280 g"))
    assert relation == "comparable"


def test_pairing_is_one_to_one():
    b = [item("blinkit", "Amul Salted Butter", "500 g")]
    i = [item("instamart", "Amul Salted Butter", "500 g"), item("instamart", "Amul Salted Butter", "500 g")]
    matches, _, unmatched_i = pair_products(b, i)
    assert len(matches) == 1
    assert len(unmatched_i) == 1


def test_unknown_size_cannot_become_exact():
    # Unknown size (None or "-") must yield 'comparable' at best, never 'exact'
    relation, _, reasons = classify(
        item("blinkit", "Coca-Cola Soft Drink", None),
        item("instamart", "Coca-Cola Soft Drink", None),
    )
    assert relation == "comparable"
    assert "one or both sizes unknown; treated as comparable" in reasons

    # One known, one unknown also cannot be exact
    relation, _, reasons = classify(
        item("blinkit", "Coca-Cola Soft Drink", None),
        item("instamart", "Coca-Cola Soft Drink", "750 ml"),
    )
    assert relation == "comparable"


def test_uncertain_first_token_does_not_hard_reject():
    # Descriptors or non-brand tokens like 'New' or 'Special' at the start
    # should NOT be treated as hard brand identity and reject the pair
    relation, score, _ = classify(
        item("blinkit", "New Maggi 2-Minute Masala Instant Noodles", "70 g"),
        item("instamart", "Maggi 2-Minute Masala Instant Noodles", "70 g"),
    )
    assert relation in ("exact", "comparable")
    assert score >= 70


def test_missing_variant_vs_conflicting_variant():
    # Missing variant: one specifies salted, the other just butter -> NOT a conflict (preserved as comparable/matchable, not rejected)
    relation_missing, score, reasons_missing = classify(
        item("blinkit", "Amul Butter", "500 g"),
        item("instamart", "Amul Pasteurised Salted Butter", "500 g"),
    )
    assert relation_missing is not None
    assert relation_missing == "comparable"
    assert "variant or brand conflict" not in reasons_missing

    # Conflicting variant: salted vs unsalted -> explicit conflict -> hard reject
    relation_conflict, _, reasons_conflict = classify(
        item("blinkit", "Amul Salted Butter", "500 g"),
        item("instamart", "Amul Unsalted Butter", "500 g"),
    )
    assert relation_conflict is None
    assert any("conflict" in r for r in reasons_conflict)

