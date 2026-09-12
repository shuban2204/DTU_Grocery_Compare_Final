from decimal import Decimal

from app.services.pricing import parse_offer_rules, price_for_quantity


def test_base_price_total():
    assert price_for_quantity(1, Decimal("18"), []) == Decimal("18")
    assert price_for_quantity(3, Decimal("18"), []) == Decimal("54")


def test_explicit_bundle_rule_uses_cheapest_combination():
    rules = parse_offer_rules("3 for ₹51")
    assert price_for_quantity(1, Decimal("19"), rules) == Decimal("19")
    assert price_for_quantity(3, Decimal("19"), rules) == Decimal("51")
    assert price_for_quantity(5, Decimal("19"), rules) == Decimal("89")


def test_vague_offer_is_not_priced_as_a_bundle():
    assert parse_offer_rules("Add more to save more") == []
