import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings, normalize_team_domain
from app.main import create_app
from tests.conftest import AUD, AUTH, EMAIL, OTHER_KEY, TEAM, build_client, make_token

HTML = {"Accept": "text/html"}
MCP = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2025-06-18",
}
LIST_TOOLS = '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'


@pytest.mark.parametrize("path", ["/", "/r/anything", "/new", "/export.json", "/plans", "/static/app.css"])
def test_pages_need_access_token(anon, path):
    r = anon.get(path, headers=HTML)
    assert r.status_code == 403
    if path != "/static/app.css":
        assert "Not signed in" in r.text


def test_fetch_and_mcp_without_token_get_401(anon):
    assert anon.get("/search?q=x", headers={"Accept": "*/*"}).status_code == 401
    r = anon.post("/mcp", headers=MCP, content=LIST_TOOLS)
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_healthz_is_public(anon):
    assert anon.get("/healthz").json() == {"ok": True}


@pytest.mark.parametrize(
    ("label", "token"),
    [
        ("wrong signing key", make_token(key=OTHER_KEY)),
        ("wrong audience", make_token(aud=["some-other-app"])),
        ("wrong issuer", make_token(iss="https://evil.cloudflareaccess.com")),
        ("expired", make_token(exp=1_000_000, iat=999_000)),
        ("no expiry", make_token(exp=None)),
        ("garbage", "not-a-jwt"),
    ],
)
def test_bad_tokens_are_refused(anon, label, token):
    r = anon.get("/", headers={**HTML, "Cf-Access-Jwt-Assertion": token})
    assert r.status_code == 403, label
    r = anon.post("/mcp", headers={**MCP, "Cf-Access-Jwt-Assertion": token}, content=LIST_TOOLS)
    assert r.status_code == 401, label


def test_unsigned_token_is_refused(anon):
    import jwt

    token = jwt.encode({"aud": AUD, "iss": f"https://{TEAM}", "exp": 9999999999, "iat": 1}, key=None, algorithm="none")
    assert anon.get("/", headers={**HTML, "Cf-Access-Jwt-Assertion": token}).status_code == 403


def test_valid_token_header_or_cookie(anon):
    r = anon.get("/", headers={**HTML, **AUTH})
    assert r.status_code == 200
    assert f'title="Signed in as {EMAIL}"' in r.text
    assert 'href="/cdn-cgi/access/logout"' in r.text
    anon.cookies.set("CF_Authorization", make_token())
    assert anon.get("/", headers=HTML).status_code == 200


def test_mcp_at_plain_path_with_token(anon):
    r = anon.post("/mcp", headers={**MCP, **AUTH}, content=LIST_TOOLS)
    assert r.status_code == 200
    assert any(t["name"] == "save_recipe" for t in r.json()["result"]["tools"])


def test_allowed_emails(settings):
    from dataclasses import replace

    with build_client(replace(settings, allowed_emails=frozenset({"someone@else.com"}))) as c:
        assert c.get("/", headers={**HTML, **AUTH}).status_code == 403
        ok = {"Cf-Access-Jwt-Assertion": make_token(email="Someone@Else.com")}
        assert c.get("/", headers={**HTML, **ok}).status_code == 200


def test_dev_no_auth(tmp_path):
    settings = Settings(public_base_url="http://testserver", db_path=tmp_path / "r.db", dev_no_auth=True)
    with TestClient(create_app(settings)) as c:
        page = c.get("/", headers=HTML)
        assert page.status_code == 200
        assert "/cdn-cgi/access/logout" not in page.text
        assert c.post("/mcp", headers=MCP, content=LIST_TOOLS).status_code == 200


def test_settings_validation(tmp_path):
    db = tmp_path / "r.db"
    with pytest.raises(ConfigError, match="CF_ACCESS_TEAM_DOMAIN"):
        Settings(public_base_url="http://x", db_path=db)
    with pytest.raises(ConfigError, match="not both"):
        Settings(public_base_url="http://x", db_path=db, dev_no_auth=True, access_team_domain=TEAM, access_aud=AUD)
    with pytest.raises(ConfigError, match="CF_ACCESS"):
        Settings(public_base_url="http://x", db_path=db, access_team_domain=TEAM)  # AUD missing


@pytest.mark.parametrize("value", ["myteam", "myteam.cloudflareaccess.com", "https://myteam.cloudflareaccess.com/"])
def test_normalize_team_domain(value):
    assert normalize_team_domain(value) == "myteam.cloudflareaccess.com"


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert "unsafe-inline" not in r.headers["content-security-policy"]
    # Refusals carry the headers too.
    anon_headers = TestClient(client.app).get("/healthz").headers
    assert anon_headers["x-content-type-options"] == "nosniff"


def test_templates_have_no_inline_script(client):
    """The CSP forbids inline script, so nothing may rely on it."""
    import re
    from pathlib import Path

    for path in Path("app/templates").glob("*.html"):
        text = path.read_text()
        assert not re.search(r"\son[a-z]+=", text), path.name
        assert not re.search(r"<script>(?!</script>)", text), path.name
