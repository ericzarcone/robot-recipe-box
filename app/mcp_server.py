"""MCP tools that let Claude save and look up recipes."""

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from app.config import Settings
from app.grocery import GroceryAisle, as_text
from app.models import PREFERRED_CATEGORIES, Recipe, RecipeFields, RecipeIn, RecipeSummary
from app.plans import MealPlan, PlanNotFound, PlanRepo, PlanSummary
from app.repo import RecipeNotFound, RecipeRepo

INSTRUCTIONS = f"""\
Robot Recipe Box is the user's personal recipe collection.
- When the user asks to save, keep, or store a recipe, call save_recipe with the complete recipe.
- Send each ingredient with separate quantity, unit, and item fields. The grocery list depends on them.
- Use one of these categories when one fits: {", ".join(PREFERRED_CATEGORIES)}.
- After you save, give the user the returned url.
- To change a saved recipe, call get_recipe, then update_recipe with only the fields that change.
- Recipes cannot be deleted with these tools. The user deletes recipes in the web app.
- Meal plans group saved recipes by weekday for one week. To plan a week, save any new recipes first,
  then call create_meal_plan with their ids. get_grocery_list combines every ingredient in a plan.
- Plan servings scale the grocery list. Set servings only when the user wants more or fewer than the recipe makes.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

IdOrSlug = Annotated[str, Field(description="Recipe id (as returned by save_recipe or search_recipes) or slug.")]


class SaveResult(BaseModel):
    id: int
    slug: str
    title: str
    category: str
    url: str
    message: str


class RecipeDetail(Recipe):
    url: str


class CategoryCount(BaseModel):
    category: str
    count: int


class PlanRecipe(BaseModel):
    id_or_slug: str = Field(..., description="Recipe id or slug.")
    day: str | None = Field(None, description="Weekday name like 'Monday'. Omit to leave it unscheduled.")
    servings: int | None = Field(None, ge=1, description="Servings to cook. Omit to use the recipe's own servings.")


class PlanDetail(MealPlan):
    url: str
    grocery_url: str


class PlanListItem(PlanSummary):
    url: str


class GroceryList(BaseModel):
    plan_id: int
    plan_name: str
    url: str
    aisles: list[GroceryAisle]
    text: str = Field(description="The list as plain text, grouped by aisle.")


PlanId = Annotated[int | None, Field(description="Meal plan id. Omit to use the most recent plan.")]


def build_mcp(repo: RecipeRepo, plans: PlanRepo, settings: Settings) -> MCPServer:
    mcp = MCPServer(name="robot-recipe-box", title="Robot Recipe Box", instructions=INSTRUCTIONS)

    def url_for(slug: str) -> str:
        return f"{settings.base_url}/r/{slug}"

    def lookup(id_or_slug: str) -> Recipe:
        try:
            return repo.get(id_or_slug.strip())
        except RecipeNotFound as exc:
            raise ToolError(f"{exc}. Use search_recipes to find the id.") from exc

    @mcp.tool(title="Save recipe", annotations=WRITE)
    def save_recipe(recipe: RecipeIn) -> SaveResult:
        """Save a new recipe to the user's recipe box. Returns a link to the saved recipe."""
        if not recipe.source:
            recipe.source = "Claude"
        saved, duplicate = repo.create(recipe)
        message = f"Saved '{saved.title}' in {saved.category}."
        if duplicate:
            message += (
                " A recipe with this title was already saved, so this is a second copy."
                " If the user wanted to change the old one, use update_recipe on it instead."
            )
        return SaveResult(
            id=saved.id,
            slug=saved.slug,
            title=saved.title,
            category=saved.category,
            url=url_for(saved.slug),
            message=message,
        )

    @mcp.tool(title="Update recipe", annotations=WRITE)
    def update_recipe(id_or_slug: IdOrSlug, changes: RecipeFields) -> SaveResult:
        """Change fields of a saved recipe. Send only the fields that change.
        A list field (ingredients, steps, tags) replaces the whole list."""
        recipe = lookup(id_or_slug)
        try:
            updated = repo.update(recipe.id, changes)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        changed = sorted(changes.model_fields_set) or ["nothing"]
        return SaveResult(
            id=updated.id,
            slug=updated.slug,
            title=updated.title,
            category=updated.category,
            url=url_for(updated.slug),
            message=f"Updated {', '.join(changed)}.",
        )

    @mcp.tool(title="Get recipe", annotations=READ_ONLY)
    def get_recipe(id_or_slug: IdOrSlug) -> RecipeDetail:
        """Get the full saved recipe, with ingredients and steps."""
        recipe = lookup(id_or_slug)
        return RecipeDetail(**recipe.model_dump(), url=url_for(recipe.slug))

    @mcp.tool(title="Search recipes", annotations=READ_ONLY)
    def search_recipes(
        query: Annotated[
            str, Field(description="Words to find in titles, ingredients, tags, or descriptions. Empty lists all.")
        ] = "",
        category: Annotated[str | None, Field(description="Only return recipes in this category.")] = None,
        favorites_only: Annotated[bool, Field(description="Only return the user's favorite recipes.")] = False,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> list[RecipeSummary]:
        """Search the saved recipes. Returns short summaries; call get_recipe for the full recipe."""
        results = repo.search(query, category=category, favorites=favorites_only, limit=limit)
        for r in results:
            r.url = url_for(r.slug)
        return results

    @mcp.tool(title="List categories", annotations=READ_ONLY)
    def list_categories() -> list[CategoryCount]:
        """List the categories in use and how many recipes each has."""
        return [CategoryCount(category=c, count=n) for c, n in repo.categories()]

    @mcp.tool(title="Set favorite", annotations=WRITE)
    def set_favorite(id_or_slug: IdOrSlug, favorite: bool = True) -> SaveResult:
        """Mark a saved recipe as a favorite, or remove it from favorites with favorite=false."""
        recipe = repo.set_favorite(lookup(id_or_slug).id, favorite)
        state = "Added to" if favorite else "Removed from"
        return SaveResult(
            id=recipe.id,
            slug=recipe.slug,
            title=recipe.title,
            category=recipe.category,
            url=url_for(recipe.slug),
            message=f"{state} favorites.",
        )

    # ---------- meal plans ----------

    def plan_detail(plan: MealPlan) -> PlanDetail:
        for item in plan.items:
            item.recipe.url = url_for(item.recipe.slug)
        base = f"{settings.base_url}/plans/{plan.id}"
        return PlanDetail(**plan.model_dump(), url=base, grocery_url=f"{base}/grocery")

    def find_plan(plan_id: int | None) -> MealPlan:
        try:
            plan = plans.get(plan_id) if plan_id is not None else plans.latest()
        except PlanNotFound as exc:
            raise ToolError(f"{exc}. Use list_meal_plans to find the id.") from exc
        if plan is None:
            raise ToolError("There are no meal plans yet. Use create_meal_plan.")
        return plan

    def add_recipes(plan_id: int, items: list[PlanRecipe]) -> None:
        for item in items:
            try:
                plans.add_item(plan_id, lookup(item.id_or_slug).id, item.day, item.servings)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc

    @mcp.tool(title="List meal plans", annotations=READ_ONLY)
    def list_meal_plans() -> list[PlanListItem]:
        """List meal plans, newest week first."""
        return [PlanListItem(**p.model_dump(), url=f"{settings.base_url}/plans/{p.id}") for p in plans.summaries()]

    @mcp.tool(title="Create meal plan", annotations=WRITE)
    def create_meal_plan(
        name: Annotated[str | None, Field(description="Omit for 'Week of <date>'.")] = None,
        week_start: Annotated[
            str | None, Field(description="Any date in the week, as YYYY-MM-DD. Omit for next week.")
        ] = None,
        recipes: Annotated[list[PlanRecipe] | None, Field(description="Saved recipes to put in the plan.")] = None,
    ) -> PlanDetail:
        """Create a weekly meal plan, optionally with recipes already in it. Recipes must be saved first."""
        for item in recipes or []:
            lookup(item.id_or_slug)  # fail before creating anything
        try:
            plan = plans.create(name, week_start)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        add_recipes(plan.id, recipes or [])
        return plan_detail(plans.get(plan.id))

    @mcp.tool(title="Add to meal plan", annotations=WRITE)
    def add_to_meal_plan(recipes: list[PlanRecipe], plan_id: PlanId = None) -> PlanDetail:
        """Add saved recipes to a meal plan. The same recipe can be added more than once."""
        plan = find_plan(plan_id)
        add_recipes(plan.id, recipes)
        return plan_detail(plans.get(plan.id))

    @mcp.tool(
        title="Remove from meal plan",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
    )
    def remove_from_meal_plan(
        item_id: Annotated[int, Field(description="The item id from get_meal_plan (items[].id), not the recipe id.")],
        plan_id: PlanId = None,
    ) -> PlanDetail:
        """Take one entry out of a meal plan. The recipe itself stays saved."""
        plan = find_plan(plan_id)
        try:
            plans.remove_item(plan.id, item_id)
        except PlanNotFound as exc:
            raise ToolError(str(exc)) from exc
        return plan_detail(plans.get(plan.id))

    @mcp.tool(title="Get meal plan", annotations=READ_ONLY)
    def get_meal_plan(plan_id: PlanId = None) -> PlanDetail:
        """Get a meal plan with its recipes by day."""
        return plan_detail(find_plan(plan_id))

    @mcp.tool(title="Get grocery list", annotations=READ_ONLY)
    def get_grocery_list(plan_id: PlanId = None) -> GroceryList:
        """Combine the ingredients of every recipe in a meal plan into one list, grouped by store aisle."""
        plan, aisles = plans.grocery(find_plan(plan_id).id)
        return GroceryList(
            plan_id=plan.id,
            plan_name=plan.name,
            url=f"{settings.base_url}/plans/{plan.id}/grocery",
            aisles=aisles,
            text=as_text(aisles),
        )

    return mcp
