import pytest

from app.models import RecipeFields, RecipeIn, normalize_category
from app.repo import RecipeNotFound, fts_query, slugify
from tests.conftest import SAMPLE


def make(repo, **overrides):
    recipe, _ = repo.create(RecipeIn(**{**SAMPLE, **overrides}))
    return recipe


def test_create_normalizes_fields(repo):
    r = make(repo)
    assert r.slug == "weeknight-chickpea-curry"
    assert r.category == "Mains"
    assert r.tags == ["vegetarian", "weeknight"]
    assert [i.raw for i in r.ingredients] == [
        "2 tbsp olive oil",
        "1 yellow onion, diced",
        "3 cloves garlic, minced",
        "2 cans chickpeas, drained",
        "1 can coconut milk",
        "1 1/2 tsp garam masala",
    ]
    garlic = r.ingredients[2]
    assert (garlic.quantity, garlic.unit, garlic.item, garlic.note) == (3, "clove", "garlic", "minced")
    assert r.ingredients[3].unit == "can"  # "cans" normalized
    assert r.ingredients[5].section == "Sauce"
    assert r.steps[2].section == "Finish"
    assert r.display_minutes == 35


def test_duplicate_titles_get_new_slug(repo):
    first, dup1 = repo.create(RecipeIn(**SAMPLE))
    second, dup2 = repo.create(RecipeIn(**SAMPLE))
    third, _ = repo.create(RecipeIn(**{**SAMPLE, "title": "weeknight chickpea curry"}))
    assert (dup1, dup2) == (False, True)
    assert [first.slug, second.slug, third.slug] == [
        "weeknight-chickpea-curry",
        "weeknight-chickpea-curry-2",
        "weeknight-chickpea-curry-3",
    ]


def test_get_by_id_or_slug(repo):
    r = make(repo)
    assert repo.get(r.id).slug == r.slug
    assert repo.get(str(r.id)).slug == r.slug
    assert repo.get(r.slug).id == r.id
    with pytest.raises(RecipeNotFound):
        repo.get("nope")


def test_update_is_partial_and_keeps_slug(repo):
    r = make(repo)
    updated = repo.update(r.slug, RecipeFields(title="Chickpea Curry (Dairy-Free)", servings=6))
    assert updated.slug == r.slug
    assert updated.title == "Chickpea Curry (Dairy-Free)"
    assert updated.servings == 6
    assert updated.ingredients == r.ingredients
    assert updated.updated_at >= r.updated_at


def test_update_rejects_empty_title(repo):
    r = make(repo)
    with pytest.raises(ValueError):
        repo.update(r.id, RecipeFields(title="   "))


def test_delete(repo):
    r = make(repo)
    repo.delete(r.id)
    with pytest.raises(RecipeNotFound):
        repo.get(r.id)
    assert repo.search("chickpea") == []


def test_search_matches_prefixes_ingredients_and_tags(repo):
    make(repo)
    make(
        repo,
        title="Lemon Bars",
        category="Desserts",
        tags=["baking"],
        description="Tart and sweet.",
        ingredients=["1 cup butter", "4 lemons"],
        steps=["Bake."],
    )
    assert [r.title for r in repo.search("chick")] == ["Weeknight Chickpea Curry"]
    assert [r.title for r in repo.search("garam")] == ["Weeknight Chickpea Curry"]
    assert [r.title for r in repo.search("lemon")] == ["Lemon Bars"]  # porter stemming: lemons -> lemon
    assert [r.title for r in repo.search("vegetarian")] == ["Weeknight Chickpea Curry"]
    assert repo.search("chickpea lemon") == []  # all words must match
    assert [r.title for r in repo.search("", category="desserts")] == ["Lemon Bars"]
    assert repo.search("curry", category="Desserts") == []
    # FTS syntax characters are treated as plain words, not as query operators.
    assert [r.title for r in repo.search('curry" (*')] == ["Weeknight Chickpea Curry"]
    assert repo.search('"NEAR( OR') == []


def test_search_ranks_title_above_ingredient(repo):
    make(repo, title="Butter Chicken", ingredients=["1 lb chicken"], tags=[], description="")
    make(repo, title="Shortbread", ingredients=["1 cup butter"], tags=[], description="", category="Baking")
    assert [r.title for r in repo.search("butter")] == ["Butter Chicken", "Shortbread"]


def test_grouped_orders_preferred_categories_first(repo):
    make(repo, title="Z Soup", category="Soups & Stews")
    make(repo, title="Pancakes", category="breakfast")
    make(repo, title="Mystery", category="weird stuff")
    make(repo, title="Another Soup", category="soups & stews")
    groups = repo.grouped()
    assert [c for c, _ in groups] == ["Breakfast", "Soups & Stews", "Weird Stuff"]
    assert [r.title for r in groups[1][1]] == ["Another Soup", "Z Soup"]
    assert repo.categories() == [("Breakfast", 1), ("Soups & Stews", 2), ("Weird Stuff", 1)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", "Uncategorized"),
        ("  mains ", "Mains"),
        ("SOUPS & STEWS", "Soups & Stews"),
        ("snacks and appetizers", "Snacks and Appetizers"),
        ("grill", "Grill"),
    ],
)
def test_normalize_category(raw, expected):
    assert normalize_category(raw) == expected


def test_slugify_and_fts_query():
    assert slugify("Crème Brûlée (Easy!)") == "creme-brulee-easy"
    assert slugify("!!!") == "recipe"
    assert fts_query("Chick peas") == '"chick"* "peas"*'
    assert fts_query("  ") is None


def test_numeric_titles_cannot_shadow_ids(repo):
    """Review finding: get(id) used to return a recipe whose slug happened to be that number."""
    pancakes = make(repo, title="Pancakes")
    decoy = make(repo, title=str(pancakes.id))
    assert decoy.slug == f"{pancakes.id}-recipe"
    for key in (pancakes.id, str(pancakes.id), f" {pancakes.id} "):
        assert repo.get(key).title == "Pancakes"
    assert repo.get(decoy.slug).id == decoy.id
    repo.update(str(pancakes.id), RecipeFields(notes="edited"))
    assert repo.get(pancakes.id).notes == "edited"
    assert repo.get(decoy.id).notes != "edited"


def test_legacy_digit_slug_still_reachable(repo):
    r = make(repo, title="Old")
    with repo.db.connect() as conn:
        conn.execute("UPDATE recipes SET slug = '999' WHERE id = ?", (r.id,))
    assert repo.get("999").id == r.id  # no recipe has id 999, so it falls back to the slug
