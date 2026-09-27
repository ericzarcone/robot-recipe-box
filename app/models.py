"""Pydantic models shared by the MCP tools, the web UI, and the repository."""

from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from app.ingredients import compose_raw, normalize_unit, parse_line

PREFERRED_CATEGORIES = [
    "Breakfast",
    "Mains",
    "Sides",
    "Soups & Stews",
    "Salads",
    "Pasta",
    "Desserts",
    "Baking",
    "Drinks",
    "Snacks & Appetizers",
    "Sauces & Condiments",
]
UNCATEGORIZED = "Uncategorized"
_SMALL_WORDS = {"&", "and", "or", "of", "with"}


def normalize_category(value: str | None) -> str:
    value = " ".join((value or "").split())
    if not value:
        return UNCATEGORIZED
    for preferred in PREFERRED_CATEGORIES:
        if value.lower() == preferred.lower():
            return preferred
    words = value.split(" ")
    return " ".join(
        w.lower() if i and w.lower() in _SMALL_WORDS else w[:1].upper() + w[1:] for i, w in enumerate(words)
    )


class Ingredient(BaseModel):
    item: str = Field("", description="The ingredient itself, without quantity or unit. Example: 'yellow onion'.")
    quantity: float | None = Field(
        None, description="Numeric amount as a decimal. Example: 1.5 for 1 1/2. Omit if none."
    )
    quantity_max: float | None = Field(None, description="Upper bound for a range like '2-3 cloves'. Usually omitted.")
    unit: str | None = Field(
        None, description="Unit such as tsp, tbsp, cup, oz, lb, g, clove, can. Omit for countable items like '2 eggs'."
    )
    note: str | None = Field(None, description="Preparation or extra detail. Example: 'finely diced'.")
    section: str | None = Field(None, description="Group heading for multi-part recipes. Example: 'Sauce'.")
    raw: str | None = Field(
        None,
        description="The ingredient line as a person would write it. Optional; built from the other fields if omitted.",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data: Any) -> Any:
        return {"raw": data} if isinstance(data, str) else data

    @model_validator(mode="after")
    def _fill_in(self) -> "Ingredient":
        """Ensure both the structured fields and the display line are present."""
        if not self.item.strip() and self.raw:
            parsed = parse_line(self.raw)
            self.item, self.quantity, self.quantity_max = parsed.item, parsed.quantity, parsed.quantity_max
            self.unit, self.note = parsed.unit, self.note or parsed.note
        self.item = self.item.strip()
        self.unit = normalize_unit(self.unit)
        if not self.raw or not self.raw.strip():
            self.raw = compose_raw(self.quantity, self.unit, self.item, self.note, self.quantity_max)
        self.raw = self.raw.strip()
        self.section = (self.section or "").strip() or None
        return self


class Step(BaseModel):
    text: str = Field(..., description="One instruction step.")
    section: str | None = Field(None, description="Group heading for multi-part recipes. Example: 'Sauce'.")

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data: Any) -> Any:
        return {"text": data} if isinstance(data, str) else data

    @field_validator("section")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class RecipeFields(BaseModel):
    """Every editable recipe field. All optional, so the same model works for partial updates."""

    title: str | None = Field(None, description="Recipe name.")
    description: str | None = Field(None, description="One or two sentences about the dish.")
    category: str | None = Field(
        None, description="One category. Prefer one of: " + ", ".join(PREFERRED_CATEGORIES) + "."
    )
    cuisine: str | None = Field(None, description="Example: Italian, Thai, Mexican.")
    tags: list[str] | None = Field(
        None, description="Short lowercase tags. Example: ['vegetarian', 'weeknight', 'one-pot']."
    )
    servings: int | None = Field(None, description="Number of servings the recipe makes.")
    yield_text: str | None = Field(
        None, description="Yield when servings do not describe it. Example: 'about 24 cookies'."
    )
    prep_minutes: int | None = Field(None, description="Active prep time in minutes.")
    cook_minutes: int | None = Field(None, description="Cook or bake time in minutes.")
    total_minutes: int | None = Field(None, description="Total time in minutes, including resting or marinating.")
    ingredients: list[Ingredient] | None = Field(None, description="Ingredients in the order they are used.")
    steps: list[Step] | None = Field(
        None, description="Instructions in order. One action or a few related actions per step."
    )
    notes: str | None = Field(None, description="Tips, substitutions, storage, or make-ahead notes.")
    source: str | None = Field(None, description="Where the recipe came from. Example: 'Claude'.")
    source_url: str | None = Field(None, description="URL of the original recipe, if any.")

    @field_validator("source_url")
    @classmethod
    def _http_url_only(cls, v: str | None) -> str | None:
        """Only web links. A javascript: or data: URL would run script in the page when clicked."""
        v = (v or "").strip()
        if not v:
            return v
        parts = urlsplit(v)
        if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
            raise ValueError("source_url must be an http:// or https:// URL")
        return v

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        seen: dict[str, None] = {}
        for tag in v:
            tag = " ".join(tag.lower().split())
            if tag:
                seen.setdefault(tag)
        return list(seen)


class RecipeIn(RecipeFields):
    """A new recipe. Title is required."""

    title: str = Field(..., min_length=1, description="Recipe name.")


class Recipe(BaseModel):
    id: int
    slug: str
    title: str
    description: str = ""
    category: str = UNCATEGORIZED
    cuisine: str = ""
    tags: list[str] = []
    servings: int | None = None
    yield_text: str = ""
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    total_minutes: int | None = None
    ingredients: list[Ingredient] = []
    steps: list[Step] = []
    notes: str = ""
    source: str = ""
    source_url: str = ""
    favorite: bool = False
    created_at: str
    updated_at: str

    @property
    def display_minutes(self) -> int | None:
        if self.total_minutes:
            return self.total_minutes
        if self.prep_minutes or self.cook_minutes:
            return (self.prep_minutes or 0) + (self.cook_minutes or 0)
        return None


class RecipeSummary(BaseModel):
    id: int
    slug: str
    title: str
    description: str
    category: str
    tags: list[str]
    servings: int | None
    total_minutes: int | None
    favorite: bool = False
    url: str = ""
