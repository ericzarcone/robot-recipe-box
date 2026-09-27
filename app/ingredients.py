"""Ingredient line parsing, unit normalization, and quantity formatting."""

import re
from dataclasses import dataclass
from fractions import Fraction

UNICODE_FRACTIONS = {
    "½": "1/2",
    "⅓": "1/3",
    "⅔": "2/3",
    "¼": "1/4",
    "¾": "3/4",
    "⅕": "1/5",
    "⅖": "2/5",
    "⅗": "3/5",
    "⅘": "4/5",
    "⅙": "1/6",
    "⅚": "5/6",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}

# Canonical unit -> spellings that map to it. Matching is case-insensitive except "T"/"t".
UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "tsp": ("tsp", "tsps", "teaspoon", "teaspoons", "t"),
    "tbsp": ("tbsp", "tbsps", "tbs", "tbl", "tablespoon", "tablespoons", "T"),
    "cup": ("cup", "cups", "c"),
    "fl oz": ("fl oz", "fl. oz", "fl. oz.", "fluid ounce", "fluid ounces"),
    "pint": ("pint", "pints", "pt"),
    "quart": ("quart", "quarts", "qt"),
    "gallon": ("gallon", "gallons", "gal"),
    "ml": ("ml", "milliliter", "milliliters", "millilitre", "millilitres"),
    "l": ("l", "liter", "liters", "litre", "litres"),
    "oz": ("oz", "ounce", "ounces"),
    "lb": ("lb", "lbs", "pound", "pounds"),
    "g": ("g", "gram", "grams"),
    "kg": ("kg", "kilogram", "kilograms"),
    "pinch": ("pinch", "pinches"),
    "dash": ("dash", "dashes"),
    "clove": ("clove", "cloves"),
    "can": ("can", "cans"),
    "jar": ("jar", "jars"),
    "package": ("package", "packages", "pkg", "packet", "packets"),
    "bunch": ("bunch", "bunches"),
    "stick": ("stick", "sticks"),
    "slice": ("slice", "slices"),
    "sprig": ("sprig", "sprigs"),
    "head": ("head", "heads"),
    "stalk": ("stalk", "stalks"),
    "piece": ("piece", "pieces"),
    "handful": ("handful", "handfuls"),
    "bag": ("bag", "bags"),
    "box": ("box", "boxes"),
    "bottle": ("bottle", "bottles"),
    "fillet": ("fillet", "fillets"),
}

_CASE_SENSITIVE = {"T": "tbsp", "t": "tsp"}
_ALIAS_TO_UNIT = {
    alias.lower(): unit for unit, aliases in UNIT_ALIASES.items() for alias in aliases if alias not in _CASE_SENSITIVE
}

# Longest first so "fl oz" wins over "fl" and "tablespoons" over "t".
_ALIASES_LONGEST_FIRST = sorted({a for aliases in UNIT_ALIASES.values() for a in aliases}, key=len, reverse=True)

# Conversion factors to a base unit per family, used to merge grocery quantities.
VOLUME_TSP = {
    "tsp": 1,
    "tbsp": 3,
    "fl oz": 6,
    "cup": 48,
    "pint": 96,
    "quart": 192,
    "gallon": 768,
    "ml": 0.202884,
    "l": 202.884,
}
WEIGHT_G = {"g": 1, "kg": 1000, "oz": 28.3495, "lb": 453.592}

_PLURAL_UNITS = {
    "cup",
    "pint",
    "quart",
    "gallon",
    "pinch",
    "dash",
    "clove",
    "can",
    "jar",
    "package",
    "bunch",
    "stick",
    "slice",
    "sprig",
    "head",
    "stalk",
    "piece",
    "handful",
    "bag",
    "box",
    "bottle",
    "fillet",
}

_NUMBER = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|\.\d+)"
_QTY_RE = re.compile(rf"^\s*(?P<qty>{_NUMBER})(?:\s*(?:-|–|to)\s*(?P<max>{_NUMBER}))?\s*")
_PAREN_SIZE_RE = re.compile(r"^\((?P<size>[^)]*)\)\s*")
_TRAILING_NOTE_RE = re.compile(
    r"\s+(?P<note>to taste|as needed|for (?:serving|garnish|garnishing|frying|dusting))\s*$", re.I
)


@dataclass
class ParsedIngredient:
    raw: str
    item: str
    quantity: float | None = None
    quantity_max: float | None = None
    unit: str | None = None
    note: str | None = None


def normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    unit = unit.strip().rstrip(".")
    if unit in _CASE_SENSITIVE:
        return _CASE_SENSITIVE[unit]
    return _ALIAS_TO_UNIT.get(unit.lower(), unit.lower())


def _to_number(text: str) -> float:
    text = text.strip()
    if " " in text:
        whole, frac = text.split(None, 1)
        return float(int(whole) + Fraction(frac))
    return float(Fraction(text))


def _replace_unicode_fractions(text: str) -> str:
    for char, ascii_frac in UNICODE_FRACTIONS.items():
        # "1½" -> "1 1/2", "½" -> "1/2"
        text = re.sub(rf"(\d){char}", rf"\1 {ascii_frac}", text)
        text = text.replace(char, ascii_frac)
    return text.replace("⁄", "/")


def _match_unit(text: str) -> tuple[str | None, str]:
    """Match a unit at the start of text. Returns (canonical unit, rest)."""
    for alias in _ALIASES_LONGEST_FIRST:
        flags = 0 if alias in _CASE_SENSITIVE else re.I
        m = re.match(rf"{re.escape(alias)}\.?(?=\s|$|,)", text, flags)
        if m:
            unit = _CASE_SENSITIVE.get(alias) if alias in _CASE_SENSITIVE else _ALIAS_TO_UNIT[alias.lower()]
            return unit, text[m.end() :].lstrip()
    return None, text


def parse_line(line: str) -> ParsedIngredient:
    """Parse a free-text ingredient line like '1 1/2 cups flour, sifted'."""
    raw = line.strip()
    text = _replace_unicode_fractions(raw.lstrip("-*• ").strip())
    quantity = quantity_max = None
    unit = None
    notes: list[str] = []

    m = _QTY_RE.match(text)
    if m:
        quantity = _to_number(m.group("qty"))
        quantity_max = _to_number(m.group("max")) if m.group("max") else None
        text = text[m.end() :]
        size = _PAREN_SIZE_RE.match(text)
        if size:
            notes.append(size.group("size").strip())
            text = text[size.end() :]
        unit, text = _match_unit(text)
        if unit and text.lower().startswith("of "):
            text = text[3:]

    if "," in text:
        text, after = text.split(",", 1)
        notes.append(after.strip())
    else:
        trailing = _TRAILING_NOTE_RE.search(text)
        if trailing:
            notes.append(trailing.group("note"))
            text = text[: trailing.start()]
    paren = re.search(r"\s*\(([^)]*)\)\s*$", text)
    if paren:
        notes.insert(0, paren.group(1).strip())
        text = text[: paren.start()]

    item = text.strip() or raw
    note = ", ".join(n for n in notes if n) or None
    return ParsedIngredient(raw=raw, item=item, quantity=quantity, quantity_max=quantity_max, unit=unit, note=note)


def format_quantity(value: float | None) -> str:
    """1.5 -> '1 1/2', 0.333 -> '1/3', 2.0 -> '2'. Uses denominators people cook with."""
    if value is None:
        return ""
    if value <= 0:
        return "0"
    whole = int(value)
    remainder = value - whole
    best = min(((abs(remainder - n / d), n, d) for d in (2, 3, 4, 8) for n in range(0, d + 1)), key=lambda t: t[0])
    err, num, den = best
    if err > 0.02:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if num == den:
        whole, num = whole + 1, 0
    frac = Fraction(num, den) if num else None
    if whole and frac:
        return f"{whole} {frac}"
    if frac:
        return str(frac)
    return str(whole)


def format_unit(unit: str | None, quantity: float | None) -> str:
    if not unit:
        return ""
    if unit in _PLURAL_UNITS and quantity is not None and quantity > 1:
        return unit + ("es" if unit.endswith(("ch", "sh", "x")) else "s")
    return unit


def compose_raw(
    quantity: float | None, unit: str | None, item: str, note: str | None, quantity_max: float | None = None
) -> str:
    """Build a display line from structured parts."""
    qty = format_quantity(quantity)
    if qty and quantity_max:
        qty = f"{qty}–{format_quantity(quantity_max)}"
    parts = [qty, format_unit(unit, quantity_max or quantity), item]
    line = " ".join(p for p in parts if p)
    return f"{line}, {note}" if note else line
