"""Combine the ingredients of several recipes into one grocery list, grouped by aisle."""

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.ingredients import VOLUME_TSP, WEIGHT_G, format_quantity, format_unit
from app.models import Ingredient, Recipe

# Words that describe preparation or size, not what to buy. Dropped when matching items.
_PREP_WORDS = {
    "fresh",
    "freshly",
    "large",
    "medium",
    "small",
    "extra-large",
    "jumbo",
    "chopped",
    "diced",
    "minced",
    "sliced",
    "finely",
    "roughly",
    "coarsely",
    "thinly",
    "grated",
    "peeled",
    "packed",
    "cold",
    "warm",
    "softened",
    "melted",
    "room-temperature",
    "cooked",
    "uncooked",
    "optional",
}
_NOT_PLURAL = {
    "asparagus",
    "couscous",
    "hummus",
    "molasses",
    "swiss",
    "citrus",
    "grits",
    "oats",
    "greens",
    "brussels",
    "lemongrass",
    "bass",
    "glass",
    "watercress",
    "chives",
}
_IRREGULAR = {"leaves": "leaf", "loaves": "loaf", "halves": "half", "knives": "knife"}
_SKIP = {"water", "ice", "ice water", "hot water", "cold water", "warm water", "boiling water"}

AISLES: list[tuple[str, tuple[str, ...]]] = [
    (
        "Meat & Seafood",
        (
            "beef",
            "pork",
            "chicken",
            "turkey",
            "lamb",
            "bacon",
            "pancetta",
            "sausage",
            "prosciutto",
            "ham",
            "chorizo",
            "salmon",
            "shrimp",
            "fish",
            "cod",
            "tuna",
            "steak",
            "thigh",
            "breast",
            "anchovy",
            "scallop",
            "crab",
            "mussel",
            "clam",
            "duck",
            "veal",
            "brisket",
        ),
    ),
    (
        "Dairy & Eggs",
        (
            "milk",
            "butter",
            "cream",
            "cheese",
            "yogurt",
            "egg",
            "parmesan",
            "parmigiano",
            "mozzarella",
            "cheddar",
            "feta",
            "ricotta",
            "mascarpone",
            "ghee",
            "buttermilk",
            "creme fraiche",
            "gruyere",
            "pecorino",
            "goat cheese",
            "half-and-half",
        ),
    ),
    (
        "Spices & Seasonings",
        (
            "salt",
            "pepper flakes",
            "peppercorn",
            "black pepper",
            "cumin",
            "paprika",
            "turmeric",
            "cinnamon",
            "nutmeg",
            "garam masala",
            "curry powder",
            "chili powder",
            "oregano",
            "thyme",
            "cayenne",
            "coriander",
            "clove",
            "cardamom",
            "bay leaf",
            "vanilla",
            "seasoning",
            "spice",
            "allspice",
            "fennel seed",
            "mustard seed",
            "za'atar",
            "sumac",
            "dried",
            "ground ginger",
            "garlic powder",
            "onion powder",
        ),
    ),
    (
        "Produce",
        (
            "onion",
            "garlic",
            "shallot",
            "scallion",
            "leek",
            "ginger",
            "tomato",
            "potato",
            "carrot",
            "celery",
            "pepper",
            "chile",
            "chili",
            "jalapeño",
            "jalapeno",
            "lettuce",
            "spinach",
            "kale",
            "arugula",
            "cabbage",
            "broccoli",
            "cauliflower",
            "zucchini",
            "squash",
            "cucumber",
            "eggplant",
            "mushroom",
            "corn",
            "pea",
            "bean sprout",
            "green bean",
            "asparagus",
            "avocado",
            "lemon",
            "lime",
            "orange",
            "apple",
            "banana",
            "berry",
            "grape",
            "mango",
            "pineapple",
            "peach",
            "pear",
            "cilantro",
            "parsley",
            "basil",
            "mint",
            "dill",
            "rosemary",
            "sage",
            "chive",
            "herb",
            "lettuce",
            "greens",
            "radish",
            "beet",
            "fennel",
            "sweet potato",
            "yam",
            "bok choy",
            "sprout",
        ),
    ),
    ("Bakery", ("bread", "baguette", "bun", "roll", "tortilla", "pita", "naan", "sourdough", "brioche", "croissant")),
    ("Frozen", ("frozen", "ice cream", "puff pastry")),
    (
        "Pantry",
        (
            "flour",
            "sugar",
            "rice",
            "pasta",
            "spaghetti",
            "noodle",
            "lasagna",
            "oil",
            "vinegar",
            "stock",
            "broth",
            "can",
            "tomato paste",
            "crushed tomato",
            "diced tomato",
            "coconut milk",
            "bean",
            "chickpea",
            "lentil",
            "oat",
            "honey",
            "maple",
            "syrup",
            "soy sauce",
            "fish sauce",
            "sauce",
            "mustard",
            "ketchup",
            "mayonnaise",
            "baking",
            "yeast",
            "cornstarch",
            "cocoa",
            "chocolate",
            "nut",
            "almond",
            "walnut",
            "pecan",
            "peanut",
            "sesame",
            "tahini",
            "raisin",
            "breadcrumb",
            "panko",
            "cracker",
            "wine",
            "quinoa",
            "couscous",
            "polenta",
            "jam",
            "olive",
            "caper",
            "salsa",
            "sriracha",
            "miso",
        ),
    ),
]
OTHER = "Other"
AISLE_ORDER = [name for name, _ in AISLES] + [OTHER]
# Checked before AISLES: specific phrases that would otherwise land in the wrong aisle
# ("tomato paste" is not produce, "garlic clove" is not a spice, "peanut butter" is not dairy).
_AISLE_OVERRIDES: list[tuple[str, tuple[str, ...]]] = [
    ("Frozen", ("ice cream", "frozen")),
    (
        "Pantry",
        (
            "canned",
            "tomato paste",
            "tomato sauce",
            "san marzano",
            "coconut milk",
            "chickpea",
            "black bean",
            "kidney bean",
            "pinto bean",
            "cannellini",
            "peanut butter",
            "olive oil",
            "sesame oil",
            "vegetable oil",
            "canola oil",
            "sun-dried tomato",
            "stock",
            "broth",
            "vinegar",
            "soy sauce",
            "chocolate",
            "sugar",
            "flour",
            "pasta",
            "rice",
            "lasagna",
            "noodle",
            "coconut cream",
        ),
    ),
    (
        "Spices & Seasonings",
        (
            "garlic powder",
            "onion powder",
            "ground ginger",
            "chili powder",
            "red pepper flake",
            "black pepper",
            "cayenne",
            "smoked paprika",
            "kosher salt",
            "sea salt",
            "flaky salt",
            "vanilla extract",
            "ground cumin",
            "ground coriander",
            "ground cinnamon",
            "ground nutmeg",
            "dried",
        ),
    ),
    ("Produce", ("garlic", "bell pepper", "green onion")),
]
# Bare names that mean the spice, not the vegetable ("salt and pepper").
_PLAIN_SPICES = {"pepper", "ground pepper", "white pepper", "salt"}
CANNED_UNITS = {"can", "jar"}
_COUNT_WORDS = ("clove", "stalk", "sprig")
# Whole things you buy by count. Totals round up: nobody buys 1/3 of an onion.
_WHOLE_UNITS = {
    "",
    "can",
    "jar",
    "package",
    "bag",
    "box",
    "bottle",
    "head",
    "bunch",
    "clove",
    "stalk",
    "fillet",
    "piece",
    "slice",
    "sprig",
    "stick",
}


def _has_word(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", text) is not None


def _singular(word: str) -> str:
    if word in _NOT_PLURAL or len(word) <= 3:
        return word
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("oes", "ches", "shes", "sses", "xes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def item_key(name: str, unit: str | None = None) -> str:
    """'Large Yellow Onions, diced' -> 'yellow onion'. Used to merge the same item across recipes.
    Canned goods get their own key, so canned and fresh tomatoes stay separate lines."""
    name = re.sub(r"\([^)]*\)", " ", name.lower())
    name = name.split(",")[0]
    words = [w for w in re.findall(r"[a-zà-ÿ'-]+", name) if w not in _PREP_WORDS]
    if words:
        words[-1] = _singular(words[-1])
    key = " ".join(words)
    if unit in CANNED_UNITS and key and "canned" not in key:
        key = f"canned {key}"
    return key


def aisle_for(key: str) -> str:
    if key in _PLAIN_SPICES:
        return "Spices & Seasonings"
    for groups in (_AISLE_OVERRIDES, AISLES):
        for aisle, phrases in groups:
            if any(_has_word(key, p) for p in phrases):
                return aisle
    return OTHER


# ---------- quantities ----------


@dataclass
class _Amounts:
    """Running totals for one item, one bucket per unit family."""

    volume_tsp: float = 0
    weight_g: float = 0
    metric_only_volume: bool = True
    metric_only_weight: bool = True
    by_unit: dict[str, float] = field(default_factory=lambda: defaultdict(float))  # count units and unknown units
    unquantified: bool = False

    def add(self, quantity: float | None, unit: str | None, scale: float) -> None:
        if quantity is None:
            self.unquantified = True
            return
        q = quantity * scale
        if unit in VOLUME_TSP:
            self.volume_tsp += q * VOLUME_TSP[unit]
            self.metric_only_volume &= unit in ("ml", "l")
        elif unit in WEIGHT_G:
            self.weight_g += q * WEIGHT_G[unit]
            self.metric_only_weight &= unit in ("g", "kg")
        else:
            self.by_unit[unit or ""] += q

    def describe(self) -> list[str]:
        parts = []
        if self.volume_tsp:
            parts.append(_describe_volume(self.volume_tsp, self.metric_only_volume))
        if self.weight_g:
            parts.append(_describe_weight(self.weight_g, self.metric_only_weight))
        for unit, q in self.by_unit.items():
            q = _round_up_count(q, unit)
            parts.append(" ".join(p for p in (format_quantity(q), format_unit(unit, q)) if p))
        if not parts and self.unquantified:
            parts.append("as needed")
        return parts


def _round_up_count(q: float, unit: str) -> float:
    if unit in _WHOLE_UNITS:
        return max(1, math.ceil(q - 0.05))
    return q


def _describe_volume(tsp: float, metric: bool) -> str:
    if metric:
        ml = tsp / VOLUME_TSP["ml"]
        return f"{ml / 1000:.2g} l" if ml >= 1000 else f"{round(ml)} ml"
    quarter_cups = tsp / 12
    # Half a cup and up reads best in cups. Below that, only exact quarter cups do.
    if tsp >= 24 or (tsp >= 12 and abs(quarter_cups - round(quarter_cups)) < 0.01):
        cups = _snap(tsp / 48, 4)
        return f"{format_quantity(cups)} {format_unit('cup', cups)}"
    if tsp >= 3:
        return f"{format_quantity(_snap(tsp / 3, 2))} tbsp"
    return f"{format_quantity(_snap(tsp, 8))} tsp"


def _describe_weight(grams: float, metric: bool) -> str:
    if metric:
        return f"{grams / 1000:.3g} kg" if grams >= 1000 else f"{round(grams)} g"
    oz = grams / WEIGHT_G["oz"]
    if oz >= 16:
        return f"{format_quantity(_snap(oz / 16, 4))} lb"
    return f"{format_quantity(_snap(oz, 2))} oz"


def _snap(value: float, denominator: int) -> float:
    """Round up to the nearest 1/denominator, so the list never says to buy less than needed."""
    return math.ceil(value * denominator - 1e-9) / denominator


# ---------- the list ----------


class GroceryItem(BaseModel):
    key: str
    name: str
    amounts: list[str]
    recipes: list[str]
    notes: list[str] = []
    checked: bool = False

    @property
    def line(self) -> str:
        amount = " + ".join(self.amounts)
        return f"{self.name} — {amount}" if amount else self.name


class GroceryAisle(BaseModel):
    name: str
    items: list[GroceryItem]


def build_grocery_list(entries: list[tuple[Recipe, float]], checked: set[str] | None = None) -> list[GroceryAisle]:
    """entries: (recipe, scale) pairs. The same recipe can appear more than once."""
    checked = checked or set()
    totals: dict[str, _Amounts] = {}
    names: dict[str, str] = {}
    sources: dict[str, dict[str, None]] = defaultdict(dict)
    for recipe, scale in entries:
        for ing in recipe.ingredients:
            for key, unit, name in _purchases(ing):
                totals.setdefault(key, _Amounts()).add(_buy_quantity(ing), unit, scale)
                names.setdefault(key, name)
                sources[key].setdefault(recipe.title)

    aisles: dict[str, list[GroceryItem]] = defaultdict(list)
    for key, amounts in totals.items():
        aisles[aisle_for(key)].append(
            GroceryItem(
                key=key,
                name=names[key],
                amounts=amounts.describe(),
                recipes=list(sources[key]),
                checked=key in checked,
            )
        )
    return [
        GroceryAisle(name=name, items=sorted(aisles[name], key=lambda i: i.name.lower()))
        for name in AISLE_ORDER
        if aisles.get(name)
    ]


def _buy_quantity(ing: Ingredient) -> float | None:
    return ing.quantity_max or ing.quantity


def _purchases(ing: Ingredient) -> list[tuple[str, str | None, str]]:
    """What to buy for one ingredient line, as (key, unit, display name) triples.
    'salt and pepper, to taste' is two things to buy; '2 cups salt and pepper chips' is not split."""
    name = ing.item or ing.raw or ""
    parts = [name]
    if ing.quantity is None and " and " in name.lower():
        parts = [p for p in re.split(r"\s+and\s+", name, flags=re.I) if p.strip()]
    result = []
    for part in parts:
        key = item_key(part, ing.unit)
        if not key or key in _SKIP:
            continue
        unit, words = ing.unit, part.split()
        # "3 garlic cloves" is the same purchase as "3 cloves garlic".
        for count_word in _COUNT_WORDS:
            if unit is None and key.endswith(f" {count_word}"):
                key, unit = key.removesuffix(f" {count_word}"), count_word
                words = words[:-1]
        result.append((key, unit, _display_name(" ".join(words), canned=key.startswith("canned "))))
    return result


def _display_name(name: str, canned: bool) -> str:
    if canned:
        # "diced tomatoes" names a product here, so keep the words as written.
        return name if "can" in name.lower() else f"{name} (canned)"
    words = [w for w in name.split() if w.lower() not in _PREP_WORDS]
    return " ".join(words) or name


def as_text(aisles: list[GroceryAisle], include_checked: bool = False) -> str:
    """Plain text for pasting into Notes or Reminders."""
    blocks = []
    for aisle in aisles:
        lines = [f"- {i.line}" for i in aisle.items if include_checked or not i.checked]
        if lines:
            blocks.append("\n".join([aisle.name, *lines]))
    return "\n\n".join(blocks)
