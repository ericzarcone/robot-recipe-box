"""Recipe storage: CRUD, slugs, categories, and full-text search."""

import json
import re
import sqlite3
import unicodedata
from datetime import UTC, datetime
from itertools import groupby

from app.db import Database
from app.models import (
    PREFERRED_CATEGORIES,
    UNCATEGORIZED,
    Recipe,
    RecipeFields,
    RecipeIn,
    RecipeSummary,
    normalize_category,
)

_JSON_FIELDS = ("tags", "ingredients", "steps")
_COLUMNS = (
    "title",
    "description",
    "category",
    "cuisine",
    "tags",
    "servings",
    "yield_text",
    "prep_minutes",
    "cook_minutes",
    "total_minutes",
    "ingredients",
    "steps",
    "notes",
    "source",
    "source_url",
)
_TEXT_DEFAULTS = {"description", "cuisine", "yield_text", "notes", "source", "source_url"}
# bm25 weights, in recipes_fts column order: title, description, category, tags, ingredients.
_BM25 = "bm25(recipes_fts, 10.0, 2.0, 3.0, 4.0, 1.0)"


class RecipeNotFound(LookupError):
    pass


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80].rstrip("-") or "recipe"
    # An all-digit slug would look like an id (see RecipeRepo.get).
    return f"{slug}-recipe" if slug.isdigit() else slug


def fts_query(text: str) -> str | None:
    """Turn user input into an FTS5 query: every word must match, as a prefix."""
    words = re.findall(r"\w+", text.lower())
    return " ".join(f'"{w}"*' for w in words) or None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _row_to_recipe(row: sqlite3.Row) -> Recipe:
    data = dict(row)
    for key in _JSON_FIELDS:
        data[key] = json.loads(data[key])
    return Recipe.model_validate(data)


def row_to_summary(row: sqlite3.Row) -> RecipeSummary:
    data = dict(row)
    data["tags"] = json.loads(data["tags"])
    prep, cook = data.pop("prep_minutes"), data.pop("cook_minutes")
    data["total_minutes"] = data["total_minutes"] or ((prep or 0) + (cook or 0)) or None
    return RecipeSummary.model_validate(data)


def _to_columns(fields: RecipeFields) -> dict[str, object]:
    """Convert the fields that were set into column values."""
    values: dict[str, object] = {}
    for name in fields.model_fields_set & set(_COLUMNS):
        value = getattr(fields, name)
        if name == "title":
            value = " ".join(value.split())
        elif name == "category":
            value = normalize_category(value)
        elif name in ("ingredients", "steps"):
            value = json.dumps([item.model_dump(exclude_none=True) for item in value or []])
        elif name == "tags":
            value = json.dumps(value or [])
        elif name in _TEXT_DEFAULTS:
            value = (value or "").strip()
        values[name] = value
    return values


SUMMARY_COLUMNS = (
    "id, slug, title, description, category, tags, servings, total_minutes, prep_minutes, cook_minutes, favorite"
)


class RecipeRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _unique_slug(self, conn: sqlite3.Connection, title: str) -> str:
        base = slugify(title)
        taken = {
            r[0] for r in conn.execute("SELECT slug FROM recipes WHERE slug = ? OR slug LIKE ?", (base, f"{base}-%"))
        }
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    def create(self, recipe: RecipeIn) -> tuple[Recipe, bool]:
        """Insert a recipe. Returns (recipe, a recipe with the same title already existed)."""
        values = _to_columns(recipe)
        values.setdefault("category", UNCATEGORIZED)
        now = _now()
        with self.db.connect() as conn:
            duplicate = (
                conn.execute("SELECT 1 FROM recipes WHERE lower(title) = lower(?)", (values["title"],)).fetchone()
                is not None
            )
            values.update(slug=self._unique_slug(conn, str(values["title"])), created_at=now, updated_at=now)
            cols = ", ".join(values)
            marks = ", ".join("?" for _ in values)
            cur = conn.execute(f"INSERT INTO recipes ({cols}) VALUES ({marks})", tuple(values.values()))
            row = conn.execute("SELECT * FROM recipes WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_recipe(row), duplicate

    def get(self, id_or_slug: int | str) -> Recipe:
        """All-digit input is an id. Anything else is a slug. New slugs are never all digits (see slugify),
        so an id can never be mistaken for another recipe's slug."""
        text = str(id_or_slug).strip()
        with self.db.connect() as conn:
            row = None
            if text.isascii() and text.isdigit():
                row = conn.execute("SELECT * FROM recipes WHERE id = ?", (int(text),)).fetchone()
            if row is None:
                row = conn.execute("SELECT * FROM recipes WHERE slug = ?", (text,)).fetchone()
        if row is None:
            raise RecipeNotFound(f"No recipe with id or slug {id_or_slug!r}")
        return _row_to_recipe(row)

    def update(self, id_or_slug: int | str, fields: RecipeFields) -> Recipe:
        recipe = self.get(id_or_slug)
        values = _to_columns(fields)
        if "title" in values and not values["title"]:
            raise ValueError("Title cannot be empty")
        if values:
            values["updated_at"] = _now()
            assignments = ", ".join(f"{k} = ?" for k in values)
            with self.db.connect() as conn:
                conn.execute(f"UPDATE recipes SET {assignments} WHERE id = ?", (*values.values(), recipe.id))
        return self.get(recipe.id)

    def delete(self, id_or_slug: int | str) -> None:
        recipe = self.get(id_or_slug)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM recipes WHERE id = ?", (recipe.id,))

    def all(self) -> list[Recipe]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM recipes ORDER BY id").fetchall()
        return [_row_to_recipe(r) for r in rows]

    def summaries(self, category: str | None = None, favorites: bool = False) -> list[RecipeSummary]:
        where, params = _filters(category, favorites)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT {SUMMARY_COLUMNS} FROM recipes r {where} ORDER BY category, title COLLATE NOCASE", params
            ).fetchall()
        return [row_to_summary(r) for r in rows]

    def grouped(self, category: str | None = None, favorites: bool = False) -> list[tuple[str, list[RecipeSummary]]]:
        """Summaries grouped by category: preferred categories first, in their listed order."""
        order = {c: i for i, c in enumerate(PREFERRED_CATEGORIES)}
        items = sorted(
            self.summaries(category, favorites), key=lambda s: (order.get(s.category, len(order)), s.category)
        )
        return [(cat, list(group)) for cat, group in groupby(items, key=lambda s: s.category)]

    def categories(self) -> list[tuple[str, int]]:
        order = {c: i for i, c in enumerate(PREFERRED_CATEGORIES)}
        with self.db.connect() as conn:
            rows = conn.execute("SELECT category, count(*) FROM recipes GROUP BY category").fetchall()
        return sorted(((r[0], r[1]) for r in rows), key=lambda c: (order.get(c[0], len(order)), c[0]))

    def search(
        self, text: str, category: str | None = None, favorites: bool = False, limit: int = 50
    ) -> list[RecipeSummary]:
        query = fts_query(text)
        if query is None:
            return self.summaries(category, favorites)[:limit]
        where, params = _filters(category, favorites)
        where = where.replace("WHERE", "AND", 1)
        columns = ", ".join("r." + c.strip() for c in SUMMARY_COLUMNS.split(","))
        sql = (
            f"SELECT {columns} FROM recipes_fts JOIN recipes r ON r.id = recipes_fts.rowid "
            f"WHERE recipes_fts MATCH ? {where} ORDER BY {_BM25} LIMIT ?"
        )
        with self.db.connect() as conn:
            rows = conn.execute(sql, [query, *params, limit]).fetchall()
        return [row_to_summary(r) for r in rows]

    def set_favorite(self, id_or_slug: int | str, favorite: bool) -> Recipe:
        recipe = self.get(id_or_slug)
        with self.db.connect() as conn:
            conn.execute("UPDATE recipes SET favorite = ? WHERE id = ?", (int(favorite), recipe.id))
        return recipe.model_copy(update={"favorite": favorite})


def _filters(category: str | None, favorites: bool) -> tuple[str, list[object]]:
    clauses, params = [], []
    if category:
        clauses.append("r.category = ?")
        params.append(normalize_category(category))
    if favorites:
        clauses.append("r.favorite = 1")
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), params
