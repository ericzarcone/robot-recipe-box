import json

import pytest
from mcp import Client

from app.mcp_server import build_mcp
from app.plans import PlanRepo
from tests.conftest import SAMPLE


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mcp(repo, settings):
    return build_mcp(repo, PlanRepo(repo.db, repo), settings)


async def call(client, name, args=None):
    return await client.call_tool(name, args or {})


@pytest.mark.anyio
async def test_tool_list_has_no_delete(mcp):
    async with Client(mcp) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == {
        "save_recipe",
        "update_recipe",
        "get_recipe",
        "search_recipes",
        "list_categories",
        "set_favorite",
        "list_meal_plans",
        "create_meal_plan",
        "add_to_meal_plan",
        "remove_from_meal_plan",
        "get_meal_plan",
        "get_grocery_list",
    }
    assert not any("delete" in n for n in names)


@pytest.mark.anyio
async def test_save_returns_link_and_flags_duplicates(mcp, repo):
    async with Client(mcp) as client:
        first = await call(client, "save_recipe", {"recipe": SAMPLE})
        second = await call(client, "save_recipe", {"recipe": SAMPLE})
    assert not first.is_error
    data = first.structured_content
    assert data["url"] == "http://testserver/r/weeknight-chickpea-curry"
    assert data["category"] == "Mains"
    assert "already saved" not in data["message"]
    assert "already saved" in second.structured_content["message"]
    assert second.structured_content["slug"] == "weeknight-chickpea-curry-2"
    assert len(repo.all()) == 2
    assert repo.get(data["id"]).source == "Claude"


@pytest.mark.anyio
async def test_save_accepts_plain_string_ingredients(mcp, repo):
    recipe = {"title": "Toast", "ingredients": ["2 slices sourdough", "1 tbsp butter"], "steps": ["Toast.", "Butter."]}
    async with Client(mcp) as client:
        result = await call(client, "save_recipe", {"recipe": recipe})
    saved = repo.get(result.structured_content["id"])
    assert [(i.quantity, i.unit, i.item) for i in saved.ingredients] == [
        (2, "slice", "sourdough"),
        (1, "tbsp", "butter"),
    ]


@pytest.mark.anyio
async def test_save_rejects_script_urls(mcp, repo):
    """A prompt-injected recipe page must not be able to plant a javascript: link."""
    async with Client(mcp) as client:
        for url in (
            "javascript:fetch('/r/x/delete',{method:'POST'})",
            "JAVASCRIPT:alert(1)",
            "data:text/html,x",
            "//x",
        ):
            result = await call(client, "save_recipe", {"recipe": {"title": "Evil", "source_url": url}})
            assert result.is_error, url
        ok = await call(client, "save_recipe", {"recipe": {"title": "Fine", "source_url": "https://example.com/r"}})
    assert not ok.is_error
    assert [r.title for r in repo.all()] == ["Fine"]


@pytest.mark.anyio
async def test_save_requires_title(mcp):
    async with Client(mcp) as client:
        result = await call(client, "save_recipe", {"recipe": {"ingredients": ["1 egg"]}})
    assert result.is_error


@pytest.mark.anyio
async def test_update_get_search_categories(mcp):
    async with Client(mcp) as client:
        saved = (await call(client, "save_recipe", {"recipe": SAMPLE})).structured_content
        updated = await call(
            client,
            "update_recipe",
            {
                "id_or_slug": str(saved["id"]),
                "changes": {"servings": 6, "tags": ["vegan"]},
            },
        )
        assert updated.structured_content["message"] == "Updated servings, tags."

        detail = (await call(client, "get_recipe", {"id_or_slug": saved["slug"]})).structured_content
        assert detail["servings"] == 6
        assert detail["tags"] == ["vegan"]
        assert len(detail["ingredients"]) == 6  # untouched
        assert detail["url"].endswith("/r/weeknight-chickpea-curry")

        found = (await call(client, "search_recipes", {"query": "coconut"})).structured_content["result"]
        assert [r["title"] for r in found] == ["Weeknight Chickpea Curry"]
        assert found[0]["url"] == detail["url"]

        cats = (await call(client, "list_categories")).structured_content["result"]
        assert cats == [{"category": "Mains", "count": 1}]


@pytest.mark.anyio
async def test_unknown_recipe_is_a_tool_error(mcp):
    async with Client(mcp) as client:
        result = await call(client, "get_recipe", {"id_or_slug": "does-not-exist"})
    assert result.is_error
    assert "search_recipes" in result.content[0].text


@pytest.mark.anyio
async def test_favorites_plans_and_grocery_list(mcp):
    async with Client(mcp) as client:
        curry = (await call(client, "save_recipe", {"recipe": SAMPLE})).structured_content
        toast = (
            await call(
                client,
                "save_recipe",
                {"recipe": {"title": "Toast", "servings": 2, "ingredients": ["2 slices bread", "1 tbsp olive oil"]}},
            )
        ).structured_content

        fav = await call(client, "set_favorite", {"id_or_slug": curry["slug"]})
        assert fav.structured_content["message"] == "Added to favorites."
        found = (await call(client, "search_recipes", {"favorites_only": True})).structured_content["result"]
        assert [r["title"] for r in found] == [curry["title"]]

        empty = await call(client, "get_grocery_list", {})
        assert empty.is_error and "create_meal_plan" in empty.content[0].text

        bad = await call(client, "create_meal_plan", {"recipes": [{"id_or_slug": "nope"}]})
        assert bad.is_error
        assert (await call(client, "list_meal_plans")).structured_content["result"] == []  # nothing half-made

        plan = (
            await call(
                client,
                "create_meal_plan",
                {
                    "week_start": "2026-10-05",
                    "recipes": [
                        {"id_or_slug": curry["slug"], "day": "Monday"},
                        {"id_or_slug": str(curry["id"]), "day": "Thu", "servings": 8},
                    ],
                },
            )
        ).structured_content
        assert plan["name"] == "Week of Oct 5"
        assert plan["url"] == f"http://testserver/plans/{plan['id']}"
        assert [(i["day"], i["servings"]) for i in plan["items"]] == [(0, None), (3, 8)]
        assert plan["items"][0]["recipe"]["url"].endswith("/r/weeknight-chickpea-curry")

        bad_day = await call(client, "add_to_meal_plan", {"recipes": [{"id_or_slug": toast["slug"], "day": "Funday"}]})
        assert bad_day.is_error and "Unknown day" in bad_day.content[0].text

        plan = (await call(client, "add_to_meal_plan", {"recipes": [{"id_or_slug": toast["slug"]}]})).structured_content
        assert len(plan["items"]) == 3  # defaults to the latest plan

        grocery = (await call(client, "get_grocery_list", {"plan_id": plan["id"]})).structured_content
        assert grocery["url"].endswith(f"/plans/{plan['id']}/grocery")
        assert "- chickpeas (canned) — 6 cans" in grocery["text"]
        assert "- olive oil — 7 tbsp" in grocery["text"]

        toast_item = next(i for i in plan["items"] if i["recipe"]["title"] == "Toast")
        plan = (await call(client, "remove_from_meal_plan", {"item_id": toast_item["id"]})).structured_content
        assert len(plan["items"]) == 2
        assert (await call(client, "remove_from_meal_plan", {"item_id": toast_item["id"]})).is_error
        assert (await call(client, "get_recipe", {"id_or_slug": "toast"})).structured_content["title"] == "Toast"


# ---------- over HTTP, through the real app ----------

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2025-06-18",
}


def rpc(client, method, params=None, path="/mcp", **headers):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post(path, headers={**HEADERS, **headers}, content=json.dumps(body))


def test_http_endpoint_saves_recipe(client):
    r = rpc(client, "tools/call", {"name": "save_recipe", "arguments": {"recipe": SAMPLE}})
    assert r.status_code == 200
    assert r.json()["result"]["structuredContent"]["url"] == "http://testserver/r/weeknight-chickpea-curry"
    # Trailing slash works too, without a redirect.
    r = rpc(client, "tools/list", path="/mcp/")
    assert r.status_code == 200


def test_http_endpoint_rejects_other_paths_and_hosts(client):
    assert rpc(client, "tools/list", path="/mcp/anything-else").status_code == 404
    assert rpc(client, "tools/list", Host="evil.example").status_code == 421
