from app.services.normalizer import parse_quantity


def test_mass_and_volume_unit_normalization():
    assert parse_quantity("0.5 kg").total_amount_base == 500
    assert parse_quantity("1 L").total_amount_base == 1000


def test_multipack_quantity_normalization():
    for value in ("4 x 70 g", "4×70g", "70 g x 4"):
        parsed = parse_quantity(value)
        assert (parsed.pack_count, parsed.item_amount_base, parsed.total_amount_base) == (4, 70, 280)


def test_pack_of_and_different_sizes():
    assert parse_quantity("Pack of 4").pack_count == 4
    assert parse_quantity("52 g").total_amount_base != parse_quantity("48 g").total_amount_base


def test_irrelevant_sponsored_candidate_filtering():
    from app.services.normalizer import is_query_relevant

    # Unrelated sponsored products for "Maggi"
    assert is_query_relevant("Maggi", "Act II Butter Delite Popcorn") is False
    assert is_query_relevant("Maggi", "Country Delight Instant Noodles") is False
    assert is_query_relevant("Maggi", "Wai Wai Ready to Eat Noodles") is False

    # Unrelated sponsored products for "Coca Cola"
    assert is_query_relevant("Coca Cola", "Kab's Potato Chips") is False
    assert is_query_relevant("Coca Cola", "4700BC Microwave Popcorn") is False
    assert is_query_relevant("Coca Cola", "Jimmy's Cocktail Mixer") is False

    # Unrelated sponsored products for "Lays"
    assert is_query_relevant("Lays", "Bingo Mad Angles Achaari Masti") is False
    assert is_query_relevant("Lays", "Crax Corn Rings") is False
    assert is_query_relevant("Lays", "Britannia 50-50 Maska Chaska") is False


def test_relevant_sponsored_candidate_retained():
    from app.services.normalizer import is_query_relevant

    # Relevant Maggi variants (even if sponsored)
    assert is_query_relevant("Maggi", "MAGGI 2-Minute Masala Noodles") is True
    assert is_query_relevant("Maggi", "Maggi Cuppa Spicy Cheesy Noodles") is True
    assert is_query_relevant("Maggi", "Maggi Special Masala Instant Noodles") is True

    # Relevant Coca-Cola variants and aliases (including Zero / Diet)
    assert is_query_relevant("Coca Cola", "Coca-Cola Soft Drink Can") is True
    assert is_query_relevant("Coca Cola", "Coca-Cola Zero Sugar Soft Drink") is True
    assert is_query_relevant("Coca Cola", "Diet Coke Soft Drink Can") is True
    assert is_query_relevant("Coke", "Coca-Cola Original Taste") is True

    # Relevant Lay's variants
    assert is_query_relevant("Lays", "Lay's India's Magic Masala Potato Chips") is True
    assert is_query_relevant("Lays", "Lay's American Style Cream & Onion Chips") is True
    assert is_query_relevant("Lays", "Lay's Wafer Style Salted Chips") is True

