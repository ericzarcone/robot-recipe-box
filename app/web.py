"""HTML pages: index, search, recipe, print, cook mode, edit."""

import re
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError

from app.models import PREFERRED_CATEGORIES, Ingredient, Recipe, RecipeIn, Step
from app.plans import DAYS, default_name, default_week_start
from app.repo import RecipeRepo
from app.templating import templates

router = APIRouter()

_STEP_NUMBER_RE = re.compile(r"^\s*(?:step\s*)?\d+[.)]\s*", re.I)


def get_repo(request: Request) -> RecipeRepo:
    return request.app.state.repo


# ---------- text <-> list conversion for the edit form ----------


def _section_heading(line: str) -> str | None:
    return line.lstrip("#").strip() or None


def _with_headings(pairs: list[tuple[str | None, str]]) -> str:
    """Lines of text, with a '## Section' line wherever the section changes."""
    lines, current = [], None
    for section, text in pairs:
        if section != current:
            lines.append(f"## {section or ''}".rstrip())
            current = section
        lines.append(text)
    return "\n".join(lines)


def ingredients_to_text(items: list[Ingredient]) -> str:
    return _with_headings([(i.section, i.raw or "") for i in items])


def steps_to_text(steps: list[Step]) -> str:
    return _with_headings([(s.section, s.text) for s in steps])


def text_to_ingredients(text: str, existing: list[Ingredient]) -> list[Ingredient]:
    """Parse one ingredient per line. Keep Claude's structured data for lines that did not change."""
    known = {(i.section, i.raw): i for i in existing}
    result, section = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            section = _section_heading(line)
            continue
        result.append(known.get((section, line)) or Ingredient(raw=line, section=section))
    return result


def text_to_steps(text: str) -> list[Step]:
    result, section = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            section = _section_heading(line)
            continue
        result.append(Step(text=_STEP_NUMBER_RE.sub("", line), section=section))
    return result


def _int_or_none(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


async def _form_to_fields(request: Request, existing: Recipe | None) -> dict:
    form = await request.form()
    get = lambda k: str(form.get(k) or "")  # noqa: E731
    return {
        "title": get("title").strip(),
        "description": get("description"),
        "category": get("category"),
        "cuisine": get("cuisine"),
        "tags": [t for t in get("tags").split(",") if t.strip()],
        "servings": _int_or_none(get("servings")),
        "yield_text": get("yield_text"),
        "prep_minutes": _int_or_none(get("prep_minutes")),
        "cook_minutes": _int_or_none(get("cook_minutes")),
        "total_minutes": _int_or_none(get("total_minutes")),
        "ingredients": text_to_ingredients(get("ingredients"), existing.ingredients if existing else []),
        "steps": text_to_steps(get("steps")),
        "notes": get("notes"),
        "source_url": get("source_url").strip(),
    }


def _form_context(repo: RecipeRepo, recipe: Recipe | None, values: dict | None = None, error: str | None = None):
    categories = list(dict.fromkeys(PREFERRED_CATEGORIES + [c for c, _ in repo.categories()]))
    if values is None and recipe is not None:
        values = recipe.model_dump()
        values["tags"] = ", ".join(recipe.tags)
        values["ingredients"] = ingredients_to_text(recipe.ingredients)
        values["steps"] = steps_to_text(recipe.steps)
    elif values is not None:
        values = {
            **values,
            "tags": ", ".join(values["tags"]),
            "ingredients": ingredients_to_text(values["ingredients"]),
            "steps": steps_to_text(values["steps"]),
        }
    return {"recipe": recipe, "values": values or {}, "categories": categories, "error": error}


# ---------- routes ----------


@router.get("/")
def index(
    request: Request, q: str = "", category: str = "", favorites: bool = False, repo: RecipeRepo = Depends(get_repo)
):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "q": q,
            "category": category,
            "favorites": favorites,
            "categories": repo.categories(),
            **_results(repo, q, category, favorites),
        },
    )


@router.get("/search")
def search(
    request: Request, q: str = "", category: str = "", favorites: bool = False, repo: RecipeRepo = Depends(get_repo)
):
    return templates.TemplateResponse(
        request,
        "_results.html",
        {
            "q": q,
            "category": category,
            "favorites": favorites,
            **_results(repo, q, category, favorites),
        },
    )


def _results(repo: RecipeRepo, q: str, category: str, favorites: bool) -> dict:
    if q.strip():
        return {"results": repo.search(q, category=category or None, favorites=favorites), "groups": None}
    return {"results": None, "groups": repo.grouped(category or None, favorites)}


@router.get("/new")
def new_recipe(request: Request, repo: RecipeRepo = Depends(get_repo)):
    return templates.TemplateResponse(
        request,
        "edit.html",
        _form_context(
            repo,
            None,
            {
                "title": "",
                "tags": [],
                "ingredients": [],
                "steps": [],
                "category": "",
            },
        ),
    )


@router.post("/new")
async def create_recipe(request: Request, repo: RecipeRepo = Depends(get_repo)):
    values = await _form_to_fields(request, None)
    try:
        recipe, _ = repo.create(RecipeIn(**values, source="Manual"))
    except ValidationError as exc:
        return templates.TemplateResponse(
            request, "edit.html", _form_context(repo, None, values, _form_error(exc)), status_code=422
        )
    return RedirectResponse(f"/r/{recipe.slug}", status_code=303)


def _form_error(exc: ValidationError) -> str:
    first = exc.errors()[0]
    if first["loc"] and first["loc"][0] == "title":
        return "A title is required."
    return str(first["msg"]).removeprefix("Value error, ")


@router.get("/r/{slug}")
def recipe_page(request: Request, slug: str, added: int | None = None, repo: RecipeRepo = Depends(get_repo)):
    plans = request.app.state.plans
    added_to = next((p for p in plans.summaries() if p.id == added), None) if added else None
    return templates.TemplateResponse(
        request,
        "recipe.html",
        {
            "recipe": repo.get(slug),
            "plans": plans.summaries()[:8],
            "added_to": added_to,
            "days": DAYS,
            "next_week": default_name(default_week_start()),
        },
    )


@router.get("/r/{slug}/print")
def print_page(request: Request, slug: str, autoprint: bool = False, repo: RecipeRepo = Depends(get_repo)):
    return templates.TemplateResponse(request, "print.html", {"recipe": repo.get(slug), "autoprint": autoprint})


@router.get("/r/{slug}/edit")
def edit_form(request: Request, slug: str, repo: RecipeRepo = Depends(get_repo)):
    return templates.TemplateResponse(request, "edit.html", _form_context(repo, repo.get(slug)))


@router.post("/r/{slug}/edit")
async def save_edit(request: Request, slug: str, repo: RecipeRepo = Depends(get_repo)):
    recipe = repo.get(slug)
    values = await _form_to_fields(request, recipe)
    try:
        # RecipeIn, not RecipeFields: an edit must keep a title.
        fields = RecipeIn(**values)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request, "edit.html", _form_context(repo, recipe, values, _form_error(exc)), status_code=422
        )
    repo.update(recipe.id, fields)
    return RedirectResponse(f"/r/{recipe.slug}", status_code=303)


@router.post("/r/{slug}/delete")
def delete_recipe(slug: str, repo: RecipeRepo = Depends(get_repo)):
    repo.delete(slug)
    return RedirectResponse("/", status_code=303)


@router.get("/export.json")
def export(repo: RecipeRepo = Depends(get_repo)):
    data = [r.model_dump() for r in repo.all()]
    filename = f"recipes-{date.today().isoformat()}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
