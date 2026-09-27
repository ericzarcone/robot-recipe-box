"""HTML pages for favorites, meal plans, and grocery lists."""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.plans import DAYS, InvalidInput, PlanRepo, default_week_start
from app.repo import RecipeRepo
from app.templating import templates
from app.web import get_repo

router = APIRouter()


def get_plans(request: Request) -> PlanRepo:
    return request.app.state.plans


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _int_or_none(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    if not (value.isascii() and value.isdigit()):
        raise InvalidInput(f"Expected a whole number, not {value!r}")
    return int(value)


# ---------- favorites ----------


@router.post("/r/{slug}/favorite")
def toggle_favorite(request: Request, slug: str, favorite: str = Form("1"), repo: RecipeRepo = Depends(get_repo)):
    recipe = repo.set_favorite(slug, favorite == "1")
    if _wants_json(request):
        return JSONResponse({"favorite": recipe.favorite})
    return RedirectResponse(f"/r/{recipe.slug}", status_code=303)


# ---------- plans ----------


@router.get("/plans")
def plan_list(request: Request, plans: PlanRepo = Depends(get_plans)):
    return templates.TemplateResponse(
        request,
        "plans.html",
        {
            "plans": plans.summaries(),
            "default_start": default_week_start().isoformat(),
        },
    )


@router.post("/plans")
def create_plan(name: str = Form(""), week_start: str = Form(""), plans: PlanRepo = Depends(get_plans)):
    plan = plans.create(name, week_start or None)
    return RedirectResponse(f"/plans/{plan.id}", status_code=303)


@router.post("/plans/add")
def add_from_recipe(
    recipe: str = Form(...),
    plan: str = Form(...),
    day: str = Form(""),
    servings: str = Form(""),
    plans: PlanRepo = Depends(get_plans),
    repo: RecipeRepo = Depends(get_repo),
):
    """The 'Add to plan' form on a recipe page. plan is a plan id or 'new'."""
    target = plans.create() if plan == "new" else plans.get(_int_or_none(plan) or 0)
    plans.add_item(target.id, recipe, day or None, _int_or_none(servings))
    return RedirectResponse(f"/r/{repo.get(recipe).slug}?added={target.id}", status_code=303)


@router.get("/plans/{plan_id}")
def plan_page(request: Request, plan_id: int, plans: PlanRepo = Depends(get_plans)):
    plan = plans.get(plan_id)
    return templates.TemplateResponse(request, "plan.html", {"plan": plan, "days": DAYS, "today": date.today()})


@router.post("/plans/{plan_id}")
def update_plan(plan_id: int, name: str = Form(""), week_start: str = Form(""), plans: PlanRepo = Depends(get_plans)):
    plans.update(plan_id, name, week_start or None)
    return RedirectResponse(f"/plans/{plan_id}", status_code=303)


@router.post("/plans/{plan_id}/delete")
def delete_plan(plan_id: int, plans: PlanRepo = Depends(get_plans)):
    plans.delete(plan_id)
    return RedirectResponse("/plans", status_code=303)


@router.get("/plans/{plan_id}/picker")
def recipe_picker(
    request: Request,
    plan_id: int,
    q: str = "",
    repo: RecipeRepo = Depends(get_repo),
    plans: PlanRepo = Depends(get_plans),
):
    """Partial: recipes to add. With no query: favorites first, then everything else."""
    plan = plans.get(plan_id)
    if q.strip():
        results = repo.search(q, limit=30)
    else:
        everything = repo.summaries()
        results = sorted(everything, key=lambda r: (not r.favorite, r.title.lower()))[:30]
    return templates.TemplateResponse(request, "_picker.html", {"plan": plan, "results": results, "days": DAYS, "q": q})


@router.post("/plans/{plan_id}/items")
def add_item(
    plan_id: int,
    recipe: str = Form(...),
    day: str = Form(""),
    servings: str = Form(""),
    plans: PlanRepo = Depends(get_plans),
):
    plans.add_item(plan_id, recipe, day or None, _int_or_none(servings))
    return RedirectResponse(f"/plans/{plan_id}", status_code=303)


@router.post("/plans/{plan_id}/items/{item_id}")
def update_item(
    plan_id: int, item_id: int, day: str = Form(""), servings: str = Form(""), plans: PlanRepo = Depends(get_plans)
):
    plans.update_item(plan_id, item_id, day or None, _int_or_none(servings))
    return RedirectResponse(f"/plans/{plan_id}#item-{item_id}", status_code=303)


@router.post("/plans/{plan_id}/items/{item_id}/delete")
def remove_item(plan_id: int, item_id: int, plans: PlanRepo = Depends(get_plans)):
    plans.remove_item(plan_id, item_id)
    return RedirectResponse(f"/plans/{plan_id}", status_code=303)


# ---------- grocery list ----------


@router.get("/plans/{plan_id}/grocery")
def grocery_page(request: Request, plan_id: int, plans: PlanRepo = Depends(get_plans)):
    plan, aisles = plans.grocery(plan_id)
    return templates.TemplateResponse(
        request,
        "grocery.html",
        {
            "plan": plan,
            "aisles": aisles,
            "item_count": sum(len(a.items) for a in aisles),
        },
    )


class CheckIn(BaseModel):
    key: str
    checked: bool


@router.post("/plans/{plan_id}/grocery/check")
def check_item(plan_id: int, body: CheckIn, plans: PlanRepo = Depends(get_plans)):
    plans.set_checked(plan_id, body.key, body.checked)
    return {"ok": True}


@router.post("/plans/{plan_id}/grocery/reset")
def reset_checks(plan_id: int, plans: PlanRepo = Depends(get_plans)):
    plans.clear_checks(plan_id)
    return RedirectResponse(f"/plans/{plan_id}/grocery", status_code=303)
