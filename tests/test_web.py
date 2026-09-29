import pytest

from app.models import RecipeIn
from app.web import ingredients_to_text, steps_to_text, text_to_ingredients, text_to_steps
from tests.conftest import SAMPLE

HTML = {"Accept": "text/html"}


@pytest.fixture
def recipe(client):
    return client.app.state.repo.create(RecipeIn(**SAMPLE))[0]


# ---------- pages ----------


def test_empty_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "No recipes yet" in r.text


def test_index_groups_by_category(client, recipe):
    r = client.get("/")
    assert "<h2>Mains" in r.text
    assert f'href="/r/{recipe.slug}"' in r.text
    assert "35 min" in r.text


def test_search_partial(client, recipe):
    r = client.get("/search?q=coco")
    assert "1 result for" in r.text
    assert recipe.title in r.text
    assert "<html" not in r.text
    assert "0 results" in client.get("/search?q=zzzz").text


def test_index_with_query_and_category(client, recipe):
    assert recipe.title in client.get("/?q=curry&category=Mains").text
    assert recipe.title not in client.get("/?category=Desserts").text


def test_recipe_page(client, recipe):
    r = client.get(f"/r/{recipe.slug}")
    assert r.status_code == 200
    assert "Start cooking" in r.text
    assert "1 1/2 tsp garam masala" in r.text
    assert "<h3>Sauce</h3>" in r.text
    assert '<ol start="3">' in r.text  # step numbering continues across sections
    assert 'data-n="3"' in r.text


def test_missing_recipe_is_404(client):
    r = client.get("/r/nope")
    assert r.status_code == 404
    assert "Recipe not found" in r.text


def test_print_page(client, recipe):
    r = client.get(f"/r/{recipe.slug}/print?autoprint=1")
    assert r.status_code == 200
    assert "data-autoprint" in r.text
    assert "Prep 10 min · Cook 25 min · Total 35 min · Serves 4" in r.text
    assert "print-fit.js" in r.text


def test_edit_round_trip_keeps_structured_ingredients(client, recipe):
    form = client.get(f"/r/{recipe.slug}/edit").text
    assert "## Sauce" in form
    r = client.post(
        f"/r/{recipe.slug}/edit",
        data={
            "title": "Better Curry",
            "category": "mains",
            "tags": "vegan, quick",
            "servings": "6",
            "ingredients": ingredients_to_text(recipe.ingredients) + "\n1 handful spinach",
            "steps": "1. Cook.\n2) Eat.",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    updated = client.app.state.repo.get(recipe.id)
    assert updated.title == "Better Curry"
    assert updated.slug == recipe.slug
    assert updated.tags == ["vegan", "quick"]
    assert updated.servings == 6
    assert updated.ingredients[:6] == recipe.ingredients
    assert (updated.ingredients[6].unit, updated.ingredients[6].item, updated.ingredients[6].section) == (
        "handful",
        "spinach",
        "Sauce",
    )
    assert [s.text for s in updated.steps] == ["Cook.", "Eat."]


def test_source_url_must_be_http(client, recipe):
    r = client.post(f"/r/{recipe.slug}/edit", data={"title": "X", "source_url": "javascript:alert(1)"})
    assert r.status_code == 422
    assert "http:// or https://" in r.text
    r = client.post("/new", data={"title": "Y", "source_url": "data:text/html,hi"})
    assert r.status_code == 422
    r = client.post(f"/r/{recipe.slug}/edit", data={"title": "X", "source_url": "https://example.com/r"})
    assert r.status_code == 200 or r.status_code == 303


def test_unsafe_source_url_already_in_db_is_not_linked(client, recipe):
    # Rows saved before validation existed: the page must not turn them into links.
    with client.app.state.repo.db.connect() as conn:
        conn.execute("UPDATE recipes SET source_url = 'javascript:alert(1)' WHERE id = ?", (recipe.id,))
    page = client.get(f"/r/{recipe.slug}").text
    assert "javascript:" not in page
    assert "Original recipe" not in page


def test_edit_requires_title(client, recipe):
    r = client.post(f"/r/{recipe.slug}/edit", data={"title": " "})
    assert r.status_code == 422


def test_new_and_delete(client):
    assert client.get("/new").status_code == 200
    r = client.post(
        "/new", data={"title": "Toast", "ingredients": "1 slice bread", "steps": "Toast it"}, follow_redirects=False
    )
    assert r.headers["location"] == "/r/toast"
    assert client.app.state.repo.get("toast").source == "Manual"
    r = client.post("/r/toast/delete", follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/r/toast").status_code == 404


def test_new_requires_title(client):
    assert client.post("/new", data={"title": ""}).status_code == 422


def test_export(client, recipe):
    r = client.get("/export.json")
    assert "attachment" in r.headers["content-disposition"]
    assert r.json()[0]["title"] == recipe.title


# ---------- form text conversion ----------


def test_section_text_round_trip():
    text = "1 egg\n## Sauce\n1 cup milk\n2 tbsp flour"
    items = text_to_ingredients(text, [])
    assert [(i.section, i.raw) for i in items] == [(None, "1 egg"), ("Sauce", "1 cup milk"), ("Sauce", "2 tbsp flour")]
    assert ingredients_to_text(items) == text
    steps = text_to_steps("Step 1. Whisk\n\n## Bake\n2. Bake it")
    assert [(s.section, s.text) for s in steps] == [(None, "Whisk"), ("Bake", "Bake it")]
    assert steps_to_text(steps) == "Whisk\n## Bake\nBake it"


# ---------- phase 2: favorites, plans, grocery ----------


def test_favorite_toggle_json_and_form(client, recipe):
    r = client.post(f"/r/{recipe.slug}/favorite", data={"favorite": "1"}, headers={"Accept": "application/json"})
    assert r.json() == {"favorite": True}
    assert "★ Favorites" in client.get("/").text
    assert recipe.title in client.get("/?favorites=1").text
    assert recipe.title in client.get("/search?q=curry&favorites=1").text
    r = client.post(f"/r/{recipe.slug}/favorite", data={"favorite": "0"}, follow_redirects=False)
    assert r.status_code == 303
    assert "No favorites yet" in client.get("/?favorites=1").text


def test_plan_pages_and_grocery(client, recipe):
    assert "No plans yet" in client.get("/plans").text

    # "Add to plan" from the recipe page, into a new plan.
    r = client.post("/plans/add", data={"recipe": str(recipe.id), "plan": "new", "day": "0"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/r/{recipe.slug}?added=")
    page = client.get(r.headers["location"]).text
    assert 'Added to <a href="/plans/' in page
    plans = client.app.state.plans
    plan = plans.latest()

    r = client.post(
        f"/plans/{plan.id}/items", data={"recipe": recipe.slug, "day": "", "servings": "8"}, follow_redirects=False
    )
    assert r.status_code == 303
    page = client.get(f"/plans/{plan.id}").text
    assert "Monday" in page and "Any day" in page and recipe.title in page

    picker = client.get(f"/plans/{plan.id}/picker?q=coco").text
    assert recipe.title in picker and "<html" not in picker

    item = plans.get(plan.id).items[1]
    client.post(f"/plans/{plan.id}/items/{item.id}", data={"day": "4", "servings": ""})
    assert plans.get(plan.id).items[1].day_name == "Friday"

    grocery = client.get(f"/plans/{plan.id}/grocery").text
    assert "Pantry" in grocery and 'data-key="canned chickpea"' in grocery
    assert "4 cans" in grocery  # 2 entries x 2 cans (the servings override was cleared above)

    assert client.post(f"/plans/{plan.id}/grocery/check", json={"key": "canned chickpea", "checked": True}).json() == {
        "ok": True
    }
    assert (
        'data-key="canned chickpea" data-line="chickpeas (canned) — 4 cans" checked'
        in client.get(f"/plans/{plan.id}/grocery").text
    )
    client.post(f"/plans/{plan.id}/grocery/reset")
    assert plans.checked(plan.id) == set()

    client.post(f"/plans/{plan.id}", data={"name": "Fall week", "week_start": "2026-10-07"})
    assert plans.get(plan.id).name == "Fall week"
    assert plans.get(plan.id).week_start == "2026-10-05"

    client.post(f"/plans/{plan.id}/items/{item.id}/delete")
    assert len(plans.get(plan.id).items) == 1
    client.post(f"/plans/{plan.id}/delete")
    assert client.get(f"/plans/{plan.id}").status_code == 404
    assert "Meal plan not found" in client.get(f"/plans/{plan.id}").text


def test_plan_routes_require_access(anon):
    for path in ("/plans", "/plans/1", "/plans/1/grocery"):
        assert anon.get(path, headers=HTML).status_code == 403
    assert anon.post("/plans/1/grocery/check", json={"key": "x", "checked": True}).status_code == 401


# ---------- bad input gives a clean error, not a 500 ----------


def test_bad_plan_inputs_are_400(client, recipe):
    plans = client.app.state.plans
    plan = plans.create()
    item = plans.add_item(plan.id, recipe.id)
    cases = [
        ("/plans/add", {"recipe": str(recipe.id), "plan": "abc"}),
        (f"/plans/{plan.id}/items/{item.id}", {"day": "funday"}),
        (f"/plans/{plan.id}/items/{item.id}", {"day": "9"}),
        (f"/plans/{plan.id}/items/{item.id}", {"servings": "-4"}),
        (f"/plans/{plan.id}/items", {"recipe": str(recipe.id), "servings": "²"}),
        (f"/plans/{plan.id}", {"week_start": "not-a-date"}),
    ]
    for path, data in cases:
        r = client.post(path, data=data)
        assert r.status_code == 400, (path, data, r.status_code)
        assert "That didn't work" in r.text
    assert len(plans.get(plan.id).items) == 1  # nothing half-applied


def test_bad_recipe_numbers(client, recipe):
    # "²" is a Unicode digit that int() rejects. It is ignored, not a crash.
    assert client.post("/new", data={"title": "Squared", "servings": "²"}, follow_redirects=False).status_code == 303
    assert client.app.state.repo.get("squared").servings is None
    r = client.post(f"/r/{recipe.slug}/edit", data={"title": "X", "servings": "0"})
    assert r.status_code == 422
    assert "Servings: Input should be greater than or equal to 1" in r.text


def test_plan_redirects_point_at_the_stored_plan(client, recipe):
    plans = client.app.state.plans
    r = client.post("/plans", data={"name": "Week"}, follow_redirects=False)
    plan_id = int(r.headers["location"].removeprefix("/plans/"))
    item = plans.add_item(plan_id, recipe.id)

    def location(path, data=None):
        return client.post(path, data=data or {}, follow_redirects=False).headers["location"]

    assert location(f"/plans/{plan_id}", {"name": "Renamed"}) == f"/plans/{plan_id}"
    assert location(f"/plans/{plan_id}/items", {"recipe": str(recipe.id)}) == f"/plans/{plan_id}"
    assert location(f"/plans/{plan_id}/items/{item.id}", {"day": "2"}) == f"/plans/{plan_id}#item-{item.id}"
    assert location(f"/plans/{plan_id}/grocery/reset") == f"/plans/{plan_id}/grocery"
    assert location(f"/plans/{plan_id}/items/{item.id}/delete") == f"/plans/{plan_id}"
    # A plan that does not exist gets a 404, not a redirect.
    assert client.post("/plans/999/grocery/reset", follow_redirects=False).status_code == 404


# ---------- plan page: "+" per day and drag between days ----------


def test_move_item_changes_only_the_day(client, recipe):
    plans = client.app.state.plans
    plan = plans.create()
    item = plans.add_item(plan.id, recipe.id, day="Mon", servings=8)
    r = client.post(f"/plans/{plan.id}/items/{item.id}/move", json={"day": 4})
    assert r.status_code == 200 and r.json() == {"ok": True}
    moved = plans.get(plan.id).items[0]
    assert (moved.day_name, moved.servings) == ("Friday", 8)  # servings kept
    assert client.post(f"/plans/{plan.id}/items/{item.id}/move", json={"day": None}).status_code == 200
    assert plans.get(plan.id).items[0].day is None
    assert client.post(f"/plans/{plan.id}/items/{item.id}/move", json={"day": 9}).status_code == 400
    assert client.post(f"/plans/{plan.id}/items/{item.id}/move", json={"day": "x"}).status_code == 422
    assert client.post(f"/plans/{plan.id}/items/999/move", json={"day": 1}).status_code == 404


def test_plan_page_has_add_buttons_and_drop_targets(client, recipe):
    plans = client.app.state.plans
    plan = plans.create()
    item = plans.add_item(plan.id, recipe.id, day="Wed")
    page = client.get(f"/plans/{plan.id}").text
    assert page.count('class="icon-btn day-add"') == 8  # seven days and "Any day"
    assert 'aria-label="Add a recipe to Wednesday"' in page
    assert page.count('class="day-items"') == 8  # every day is a drop target, even empty ones
    assert 'id="day-any" data-day=""' in page
    assert f'data-item="{item.id}"' in page
    assert f'aria-label="Drag {recipe.title} to another day"' in page


def test_picker_preselects_the_day(client, recipe):
    plan = client.app.state.plans.create()
    html = client.get(f"/plans/{plan.id}/picker?day=3").text
    assert '<option value="3" selected>Thu</option>' in html
    assert " selected>" not in client.get(f"/plans/{plan.id}/picker").text
    assert client.get(f"/plans/{plan.id}/picker?day=funday").status_code == 400
