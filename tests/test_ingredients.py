import pytest

from app.ingredients import compose_raw, format_quantity, normalize_unit, parse_line


@pytest.mark.parametrize(
    ("line", "quantity", "unit", "item", "note"),
    [
        ("1 1/2 cups flour, sifted", 1.5, "cup", "flour", "sifted"),
        ("2 (15 oz) cans chickpeas, drained", 2, "can", "chickpeas", "15 oz, drained"),
        ("salt to taste", None, None, "salt", "to taste"),
        ("½ tsp ground cumin", 0.5, "tsp", "ground cumin", None),
        ("1½ T butter", 1.5, "tbsp", "butter", None),
        ("1 t salt", 1, "tsp", "salt", None),
        ("2 tablespoons of olive oil", 2, "tbsp", "olive oil", None),
        ("3 large eggs", 3, None, "large eggs", None),
        ("1 lb ground beef (80/20)", 1, "lb", "ground beef", "80/20"),
        ("4 carrots", 4, None, "carrots", None),
        ("2 cups chicken stock", 2, "cup", "chicken stock", None),
        ("- 1 bunch cilantro", 1, "bunch", "cilantro", None),
        ("Fresh parsley, for garnish", None, None, "Fresh parsley", "for garnish"),
        ("250 g spaghetti", 250, "g", "spaghetti", None),
        ("1 fl oz lime juice", 1, "fl oz", "lime juice", None),
    ],
)
def test_parse_line(line, quantity, unit, item, note):
    parsed = parse_line(line)
    assert parsed.raw == line.strip()
    assert parsed.quantity == quantity
    assert parsed.unit == unit
    assert parsed.item == item
    assert parsed.note == note


def test_parse_range():
    parsed = parse_line("2-3 cloves garlic")
    assert (parsed.quantity, parsed.quantity_max, parsed.unit, parsed.item) == (2, 3, "clove", "garlic")


def test_parse_does_not_mistake_words_for_units():
    # "c" is an alias for cup, but not inside a word.
    assert parse_line("2 carrots").unit is None
    assert parse_line("1 can tomatoes").unit == "can"


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1.5, "1 1/2"),
        (0.333, "1/3"),
        (2.0, "2"),
        (0.125, "1/8"),
        (3.75, "3 3/4"),
        (0.7, "0.7"),
        (1.99, "2"),
        (None, ""),
    ],
)
def test_format_quantity(value, text):
    assert format_quantity(value) == text


def test_normalize_unit():
    assert normalize_unit("Tablespoons") == "tbsp"
    assert normalize_unit("T") == "tbsp"
    assert normalize_unit("t") == "tsp"
    assert normalize_unit("lbs.") == "lb"
    assert normalize_unit("thingamajig") == "thingamajig"
    assert normalize_unit(None) is None


def test_compose_raw_pluralizes_units():
    assert compose_raw(2, "can", "chickpeas", "drained") == "2 cans chickpeas, drained"
    assert compose_raw(1, "can", "coconut milk", None) == "1 can coconut milk"
    assert compose_raw(2, "bunch", "kale", None) == "2 bunches kale"
    assert compose_raw(2, "tbsp", "oil", None) == "2 tbsp oil"
    assert compose_raw(None, None, "salt", "to taste") == "salt, to taste"
