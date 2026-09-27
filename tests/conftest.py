import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.access import AccessVerifier
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.repo import RecipeRepo

TEAM = "testteam.cloudflareaccess.com"
AUD = "test-aud-tag-0123456789"
EMAIL = "cook@example.com"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticKeys:
    """Stands in for PyJWKClient: always returns the test public key."""

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=SIGNING_KEY.public_key())


def make_token(key=SIGNING_KEY, **overrides) -> str:
    now = int(time.time())
    claims = {"aud": [AUD], "iss": f"https://{TEAM}", "email": EMAIL, "iat": now, "exp": now + 600, "sub": "u1"}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


AUTH = {"Cf-Access-Jwt-Assertion": make_token()}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        public_base_url="http://testserver",
        db_path=tmp_path / "recipes.db",
        access_team_domain=TEAM,
        access_aud=AUD,
    )


@pytest.fixture
def repo(settings) -> RecipeRepo:
    db = Database(settings.db_path)
    db.migrate()
    return RecipeRepo(db)


def build_client(settings) -> TestClient:
    return TestClient(create_app(settings, AccessVerifier(settings, keys=StaticKeys())))


@pytest.fixture
def anon(settings):
    """A client whose requests did not come through Cloudflare Access."""
    with build_client(settings) as c:
        yield c


@pytest.fixture
def client(anon):
    """A client whose requests carry a valid Access JWT, as if Cloudflare forwarded them."""
    anon.headers.update({"Cf-Access-Jwt-Assertion": make_token()})
    return anon


SAMPLE = {
    "title": "Weeknight Chickpea Curry",
    "description": "A fast, creamy curry from pantry staples.",
    "category": "mains",
    "cuisine": "Indian",
    "tags": ["Vegetarian", "weeknight", "vegetarian"],
    "servings": 4,
    "prep_minutes": 10,
    "cook_minutes": 25,
    "ingredients": [
        {"quantity": 2, "unit": "tbsp", "item": "olive oil"},
        {"quantity": 1, "item": "yellow onion", "note": "diced"},
        "3 cloves garlic, minced",
        {"quantity": 2, "unit": "cans", "item": "chickpeas", "note": "drained"},
        {"quantity": 1, "unit": "can", "item": "coconut milk", "section": "Sauce"},
        {"raw": "1 1/2 tsp garam masala", "section": "Sauce"},
    ],
    "steps": [
        "Heat the oil and cook the onion until soft.",
        {"text": "Add garlic and spices; cook 1 minute."},
        {"text": "Stir in coconut milk and chickpeas. Simmer 15 minutes.", "section": "Finish"},
    ],
    "notes": "Keeps 4 days in the fridge.",
}
