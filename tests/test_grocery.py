from datetime import date

import pytest

from app.grocery import aisle_for, as_text, build_grocery_list, item_key
from app.models import Recipe, RecipeIn
from app.plans import PlanNotFound, PlanRepo, default_name, default_week_start, parse_day
from tests.conftest import SAMPLE


def recipe(title, ingredients, servings=4, id=1) -> Recipe:
    return Recipe(
        id=id,
        slug=title.lower(),
        title=title,
        servings=servings,
        ingredients=ingredients,
        created_at="2026-01-01",
        updated_at="2026-01-01",
    )


def as_dict(aisles):
    return {i.name: i.amounts for a in aisles for i in a.items}


def test_merges_same_item_across_units_and_recipes():
    a = recipe("A", ["2 tbsp olive oil", "1 cup milk", "1 yellow onion, diced", "3 cloves garlic", "1 lb ground beef"])
    b = recipe(
        "B", ["1/4 cup olive oil", "1/2 cup whole milk", "2 large yellow onions", "2 garlic cloves", "8 oz ground beef"]
    )
    items = as_dict(build_grocery_list([(a, 1), (b, 1)]))
    assert items["olive oil"] == ["6 tbsp"]  # 2 tbsp + 1/4 cup
    assert items["yellow onion"] == ["3"]
    assert items["garlic"] == ["5 cloves"]
    assert items["ground beef"] == ["1 1/2 lb"]
    # "milk" and "whole milk" are different things to buy.
    assert items["milk"] == ["1 cup"] and items["whole milk"] == ["1/2 cup"]


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["1 tsp oil", "1/2 tsp oil"], "1 1/2 tsp"),
        (["2 tsp oil", "2 tsp oil"], "1 1/2 tbsp"),  # 4 tsp -> round up to 1/2 tbsp
        (["2 tbsp oil", "2 tbsp oil"], "1/4 cup"),  # exact quarter cups read as cups
        (["1 cup oil", "1 tbsp oil"], "1 1/4 cups"),  # over a cup: round up to 1/4 cup
        (["1 quart oil"], "4 cups"),
    ],
)
def test_volume_is_summed_in_one_unit(lines, expected):
    assert as_dict(build_grocery_list([(recipe("A", lines), 1)]))["oil"] == [expected]


def test_scaling_by_servings_and_rounding_up_whole_items():
    a = recipe("A", ["2 eggs", "1 can chickpeas", "1 tsp salt"], servings=4)
    items = as_dict(build_grocery_list([(a, 1.5)]))
    assert items["eggs"] == ["3"]
    assert items["chickpeas (canned)"] == ["2 cans"]  # 1.5 cans -> buy 2
    assert items["salt"] == ["1 1/2 tsp"]


def test_unmergeable_units_are_listed_together():
    a = recipe("A", ["1 bunch cilantro"])
    b = recipe("B", ["2 tbsp cilantro, chopped"])
    assert as_dict(build_grocery_list([(a, 1), (b, 1)]))["cilantro"] == ["2 tbsp", "1 bunch"]


def test_to_taste_items_and_skipped_items():
    a = recipe("A", ["salt, to taste", "1 cup water", "pepper"])
    b = recipe("B", ["1 tsp salt"])
    items = as_dict(build_grocery_list([(a, 1)]))
    assert items == {"salt": ["as needed"], "pepper": ["as needed"]}
    assert as_dict(build_grocery_list([(a, 1), (b, 1)]))["salt"] == ["1 tsp"]


def test_splits_unquantified_pairs_and_drops_repeated_units():
    a = recipe("A", ["salt and pepper, to taste", "1 tsp salt", "Feta and parsley, for serving", "2 celery stalks"])
    items = as_dict(build_grocery_list([(a, 1)]))
    assert items == {
        "salt": ["1 tsp"],
        "pepper": ["as needed"],
        "Feta": ["as needed"],
        "parsley": ["as needed"],
        "celery": ["2 stalks"],
    }
    # With a quantity, "and" is part of the name.
    assert "half and half" in as_dict(build_grocery_list([(recipe("B", ["1 cup half and half"]), 1)]))


def test_canned_and_fresh_stay_separate():
    a = recipe("A", ["1 (28 oz) can diced tomatoes", "2 tomatoes"])
    items = as_dict(build_grocery_list([(a, 1)]))
    assert items == {"diced tomatoes (canned)": ["1 can"], "tomatoes": ["2"]}


def test_metric_stays_metric():
    a = recipe("A", ["200 g spaghetti", "300 g spaghetti", "250 ml stock"])
    items = as_dict(build_grocery_list([(a, 1)]))
    assert items["spaghetti"] == ["500 g"]
    assert items["stock"] == ["250 ml"]


def test_aisles_order_and_recipe_sources():
    a = recipe(
        "Curry", ["1 onion", "1 can coconut milk", "1 tsp cumin", "1 lb chicken thighs", "2 eggs", "1 thingamajig"]
    )
    b = recipe("Salad", ["1 onion"])
    aisles = build_grocery_list([(a, 1), (b, 1)], checked={"onion"})
    assert [x.name for x in aisles] == [
        "Meat & Seafood",
        "Dairy & Eggs",
        "Spices & Seasonings",
        "Produce",
        "Pantry",
        "Other",
    ]
    onion = next(i for x in aisles for i in x.items if i.key == "onion")
    assert onion.recipes == ["Curry", "Salad"]
    assert onion.checked
    text = as_text(aisles)
    assert "onion" not in text  # checked items are left out
    assert "Pantry\n- coconut milk (canned) — 1 can" in text


@pytest.mark.parametrize(
    ("name", "aisle"),
    [
        ("eggplant", "Produce"),
        ("peanut butter", "Pantry"),
        ("unsalted butter", "Dairy & Eggs"),
        ("garlic clove", "Produce"),
        ("garlic powder", "Spices & Seasonings"),
        ("ground nutmeg", "Spices & Seasonings"),
        ("red bell pepper", "Produce"),
        ("pepper", "Spices & Seasonings"),
        ("jalapeño pepper", "Produce"),
        ("vanilla ice cream", "Frozen"),
        ("sourdough bread", "Bakery"),
    ],
)
def test_aisle_for(name, aisle):
    assert aisle_for(item_key(name)) == aisle


def test_item_key():
    assert item_key("Large Yellow Onions, diced") == "yellow onion"
    assert item_key("berries") == "berry"
    assert item_key("bay leaves") == "bay leaf"
    assert item_key("asparagus") == "asparagus"
    assert item_key("chickpeas", "can") == "canned chickpea"


# ---------- plans ----------


@pytest.fixture
def plans(repo):
    return PlanRepo(repo.db, repo)


def test_parse_day():
    assert parse_day("Monday") == 0
    assert parse_day("tue") == 1
    assert parse_day("SU") == 6
    assert parse_day(3) == 3
    assert parse_day("4") == 4
    assert parse_day("") is None
    for bad in ("x", "Funday", 9, "m"):
        with pytest.raises(ValueError):
            parse_day(bad)


def test_default_week_start():
    assert default_week_start(date(2026, 9, 28)) == date(2026, 9, 28)  # a Monday
    assert default_week_start(date(2026, 9, 26)) == date(2026, 9, 28)  # Saturday -> next Monday
    assert default_name(date(2026, 10, 5)) == "Week of Oct 5"


def test_plan_lifecycle_and_grocery(plans, repo):
    curry, _ = repo.create(RecipeIn(**SAMPLE))
    toast, _ = repo.create(RecipeIn(title="Toast", servings=2, ingredients=["2 slices bread", "1 tbsp olive oil"]))
    plan = plans.create(week_start="2026-10-01")  # a Thursday snaps back to Monday
    assert plan.week_start == "2026-09-28"
    assert plan.name == "Week of Sep 28"

    plans.add_item(plan.id, curry.slug, day="Mon")
    plans.add_item(plan.id, curry.id, day="thursday", servings=8)  # double batch
    item = plans.add_item(plan.id, toast.id)
    assert item.day is None and item.scale == 1

    plan = plans.get(plan.id)
    assert [(i.day_name, i.recipe.title, i.scale) for i in plan.items] == [
        ("Monday", curry.title, 1),
        ("Thursday", curry.title, 2),
        (None, "Toast", 1),
    ]
    by_day = plan.by_day()
    assert len(by_day) == 8 and by_day[0][1][0].recipe.title == curry.title and by_day[7][1][0].recipe.title == "Toast"
    assert plan.date_for(3) == date(2026, 10, 1)

    _, aisles = plans.grocery(plan.id)
    items = as_dict(aisles)
    assert items["chickpeas (canned)"] == ["6 cans"]  # 2 cans x (1 + 2)
    assert items["olive oil"] == ["7 tbsp"]  # 2 tbsp x 3 + 1 tbsp
    assert items["garam masala"] == ["1 1/2 tbsp"]  # 1.5 tsp x 3 = 4.5 tsp

    plans.set_checked(plan.id, "garam masala", True)
    plans.set_checked(plan.id, "garam masala", True)  # idempotent
    assert plans.checked(plan.id) == {"garam masala"}
    plans.set_checked(plan.id, "garam masala", False)
    assert plans.checked(plan.id) == set()

    plans.update_item(plan.id, item.id, day="sat", servings=None)
    assert plans.get(plan.id).items[-1].day_name == "Saturday"
    plans.remove_item(plan.id, item.id)
    assert len(plans.get(plan.id).items) == 2
    with pytest.raises(PlanNotFound):
        plans.remove_item(plan.id, item.id)

    assert [p.recipe_count for p in plans.summaries()] == [2]
    assert plans.latest().id == plan.id

    # Deleting a recipe removes it from plans.
    repo.delete(curry.id)
    assert plans.get(plan.id).items == []
    plans.delete(plan.id)
    with pytest.raises(PlanNotFound):
        plans.get(plan.id)


def test_favorites(repo):
    curry, _ = repo.create(RecipeIn(**SAMPLE))
    repo.create(RecipeIn(title="Toast"))
    assert repo.set_favorite(curry.slug, True).favorite
    assert repo.get(curry.id).favorite
    assert [r.title for r in repo.summaries(favorites=True)] == [curry.title]
    assert [r.title for r in repo.search("curry", favorites=True)] == [curry.title]
    assert repo.search("toast", favorites=True) == []
    repo.set_favorite(curry.id, False)
    assert repo.summaries(favorites=True) == []
