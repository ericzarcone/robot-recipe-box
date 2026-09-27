"""Weekly meal plans: recipes batched by day, plus grocery list check-offs."""

from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel

from app.db import Database
from app.grocery import GroceryAisle, build_grocery_list
from app.models import RecipeSummary
from app.repo import SUMMARY_COLUMNS, RecipeRepo, row_to_summary

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class PlanNotFound(LookupError):
    pass


class InvalidInput(ValueError):
    """Bad day, date, or servings value. The web app shows it as a 400, the MCP tools as a tool error."""


class PlanItem(BaseModel):
    id: int
    day: int | None
    servings: int | None
    recipe: RecipeSummary

    @property
    def day_name(self) -> str | None:
        return DAYS[self.day] if self.day is not None else None

    @property
    def scale(self) -> float:
        if self.servings and self.recipe.servings:
            return self.servings / self.recipe.servings
        return 1.0


class MealPlan(BaseModel):
    id: int
    name: str
    week_start: str | None
    created_at: str
    updated_at: str
    items: list[PlanItem] = []

    def date_for(self, day: int) -> date | None:
        return date.fromisoformat(self.week_start) + timedelta(days=day) if self.week_start else None

    def by_day(self) -> list[tuple[int | None, list[PlanItem]]]:
        """Monday..Sunday (always all seven), then unscheduled items."""
        days: list[tuple[int | None, list[PlanItem]]] = [(d, [i for i in self.items if i.day == d]) for d in range(7)]
        days.append((None, [i for i in self.items if i.day is None]))
        return days


class PlanSummary(BaseModel):
    id: int
    name: str
    week_start: str | None
    recipe_count: int
    updated_at: str


def parse_day(value: str | int | None) -> int | None:
    """Accept 0-6, 'mon', 'Monday', or empty for no day."""
    if value is None or value == "":
        return None
    if isinstance(value, int) or str(value).strip().isdigit():
        day = int(value)
        if 0 <= day <= 6:
            return day
        raise InvalidInput(f"Day number must be 0 (Monday) to 6 (Sunday), not {day}")
    text = str(value).strip().lower()
    for i, name in enumerate(DAYS):
        if len(text) >= 2 and name.lower().startswith(text):
            return i
    raise InvalidInput(f"Unknown day {value!r}. Use a weekday name like 'Monday'.")


def default_week_start(today: date | None = None) -> date:
    """Today if it is Monday, otherwise the next Monday."""
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def default_name(week_start: date | None) -> str:
    return f"Week of {week_start:%b} {week_start.day}" if week_start else "Meal plan"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class PlanRepo:
    def __init__(self, db: Database, recipes: RecipeRepo) -> None:
        self.db = db
        self.recipes = recipes

    # ---------- plans ----------

    def create(self, name: str | None = None, week_start: date | str | None = None) -> MealPlan:
        start = _as_date(week_start) if week_start else default_week_start()
        now = _now()
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO meal_plans (name, week_start, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ((name or "").strip() or default_name(start), start.isoformat(), now, now),
            )
        return self.get(cur.lastrowid)

    def get(self, plan_id: int) -> MealPlan:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM meal_plans WHERE id = ?", (plan_id,)).fetchone()
            if row is None:
                raise PlanNotFound(f"No meal plan with id {plan_id}")
            columns = ", ".join(f"r.{c.strip()}" for c in SUMMARY_COLUMNS.split(","))
            items = conn.execute(
                f"SELECT i.id AS item_id, i.day AS item_day, i.servings AS item_servings, {columns} "
                "FROM meal_plan_items i JOIN recipes r ON r.id = i.recipe_id "
                "WHERE i.plan_id = ? ORDER BY i.day IS NULL, i.day, i.id",
                (plan_id,),
            ).fetchall()
        plan = MealPlan.model_validate(dict(row))
        for item in items:
            data = dict(item)
            plan.items.append(
                PlanItem(
                    id=data.pop("item_id"),
                    day=data.pop("item_day"),
                    servings=data.pop("item_servings"),
                    recipe=row_to_summary(data),
                )
            )
        return plan

    def latest(self) -> MealPlan | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM meal_plans ORDER BY week_start IS NULL, week_start DESC, id DESC LIMIT 1"
            ).fetchone()
        return self.get(row[0]) if row else None

    def summaries(self) -> list[PlanSummary]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT p.id, p.name, p.week_start, p.updated_at, count(i.id) AS recipe_count "
                "FROM meal_plans p LEFT JOIN meal_plan_items i ON i.plan_id = p.id "
                "GROUP BY p.id ORDER BY p.week_start IS NULL, p.week_start DESC, p.id DESC"
            ).fetchall()
        return [PlanSummary.model_validate(dict(r)) for r in rows]

    def update(self, plan_id: int, name: str | None = None, week_start: date | str | None = None) -> MealPlan:
        plan = self.get(plan_id)
        new_name = (name or "").strip() or plan.name
        new_start = _as_date(week_start).isoformat() if week_start else plan.week_start
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE meal_plans SET name = ?, week_start = ?, updated_at = ? WHERE id = ?",
                (new_name, new_start, _now(), plan_id),
            )
        return self.get(plan_id)

    def delete(self, plan_id: int) -> None:
        self.get(plan_id)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM meal_plans WHERE id = ?", (plan_id,))

    # ---------- items ----------

    def add_item(
        self, plan_id: int, recipe: int | str, day: str | int | None = None, servings: int | None = None
    ) -> PlanItem:
        self.get(plan_id)
        recipe_id = self.recipes.get(recipe).id
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO meal_plan_items (plan_id, recipe_id, day, servings, created_at) VALUES (?, ?, ?, ?, ?)",
                (plan_id, recipe_id, parse_day(day), _check_servings(servings), _now()),
            )
            conn.execute("UPDATE meal_plans SET updated_at = ? WHERE id = ?", (_now(), plan_id))
        return next(i for i in self.get(plan_id).items if i.id == cur.lastrowid)

    def update_item(self, plan_id: int, item_id: int, day: str | int | None, servings: int | None) -> None:
        self._touch_item(
            plan_id,
            item_id,
            "UPDATE meal_plan_items SET day = ?, servings = ? WHERE id = ? AND plan_id = ?",
            (parse_day(day), _check_servings(servings), item_id, plan_id),
        )

    def remove_item(self, plan_id: int, item_id: int) -> None:
        self._touch_item(
            plan_id, item_id, "DELETE FROM meal_plan_items WHERE id = ? AND plan_id = ?", (item_id, plan_id)
        )

    def _touch_item(self, plan_id: int, item_id: int, sql: str, params: tuple) -> None:
        with self.db.connect() as conn:
            if conn.execute(sql, params).rowcount == 0:
                raise PlanNotFound(f"No item {item_id} in meal plan {plan_id}")
            conn.execute("UPDATE meal_plans SET updated_at = ? WHERE id = ?", (_now(), plan_id))

    # ---------- grocery list ----------

    def grocery(self, plan_id: int) -> tuple[MealPlan, list[GroceryAisle]]:
        plan = self.get(plan_id)
        full = {r_id: self.recipes.get(r_id) for r_id in {i.recipe.id for i in plan.items}}
        entries = [(full[i.recipe.id], i.scale) for i in plan.items]
        return plan, build_grocery_list(entries, self.checked(plan_id))

    def checked(self, plan_id: int) -> set[str]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT item_key FROM grocery_checks WHERE plan_id = ?", (plan_id,)).fetchall()
        return {r[0] for r in rows}

    def set_checked(self, plan_id: int, key: str, checked: bool) -> None:
        self.get(plan_id)
        with self.db.connect() as conn:
            if checked:
                conn.execute("INSERT OR IGNORE INTO grocery_checks (plan_id, item_key) VALUES (?, ?)", (plan_id, key))
            else:
                conn.execute("DELETE FROM grocery_checks WHERE plan_id = ? AND item_key = ?", (plan_id, key))

    def clear_checks(self, plan_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM grocery_checks WHERE plan_id = ?", (plan_id,))


def _check_servings(servings: int | None) -> int | None:
    """None or 0 = use the recipe's own servings."""
    if servings is not None and servings < 0:
        raise InvalidInput(f"Servings must be 1 or more, not {servings}")
    return servings or None


def _as_date(value: date | str) -> date:
    """Parse a date and move it back to the Monday of its week, so day names line up."""
    if not isinstance(value, date):
        try:
            value = date.fromisoformat(value.strip())
        except ValueError as exc:
            raise InvalidInput(f"Dates must look like 2026-09-28, not {value!r}") from exc
    return value - timedelta(days=value.weekday())
