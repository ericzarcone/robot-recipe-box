# Robot Recipe Box

A small self-hosted recipe box. Claude (web, desktop, or mobile) saves recipes to it through an MCP connector. You browse, search, print, and cook from them on your phone or computer.

- **MCP server**: Claude can save, update, search, and favorite recipes, build weekly meal plans, and read the combined grocery list. Claude cannot delete recipes.
- **Index and search**: recipes grouped by category, live full-text search over titles, ingredients, and tags.
- **One-page print**: the print view shrinks the text until the recipe fits on one US Letter page.
- **Cooking mode**: keeps the screen on (Screen Wake Lock API), shows larger text, and lets you tap to check off ingredients and steps.
- **Favorites, meal plans, grocery list**: put recipes on days of the week, scale servings, and get one combined list grouped by aisle. Check items off as you shop, then share, copy, or print what is left.

Stack: Python 3.13, FastAPI, the official `mcp` SDK (streamable HTTP, stateless), SQLite with FTS5, and Jinja templates. There is no JavaScript build step.

## How access works

Cloudflare Access sits in front of the whole site, and the app trusts nothing else:

- **You, in a browser:** Access asks you to log in (email one-time PIN, Google, GitHub, …), then forwards your requests with a signed JWT.
- **Claude's connector:** Access's **Managed OAuth** lets Claude log in with the same policy. When you add the connector, a browser window opens, you log in through Access once, and Claude's requests then arrive with the same kind of JWT.
- **The app:** checks the JWT on every request, web pages and `/mcp` alike. It verifies the signature against your team's public keys, the application's AUD tag, the issuer, and the expiry. A request that skips Cloudflare, for example straight to port 8000 on your LAN, is refused.

There is no app password and no secret URL. To lock everyone out, change the Access policy.

## Set it up

### 1. Tunnel

1. In Cloudflare, go to **Zero Trust → Networks → Tunnels** and create a tunnel. Copy its token into `TUNNEL_TOKEN`.
2. Add a **public hostname**, for example `recipes.example.com`, with the service `http://app:8000`.

### 2. Access application

1. Go to **Zero Trust → Access controls → Applications → Add an application → Self-hosted**. Set the domain to `recipes.example.com`, with the path left empty so it covers the whole site.
2. Add a policy: action **Allow**, include **Emails**, and list your address and anyone else who should get in.
3. **Session duration:** pick something long, such as 1 month, so your phone does not ask you to log in again mid-recipe.
4. Under **Advanced settings**, turn on **Managed OAuth**.
   - Under **Allowed redirect URIs**, add `https://claude.ai/api/mcp/auth_callback`.
   - **Grant session duration:** pick something long, such as 30 days or more. This is how long Claude stays connected before you must reconnect the connector.
5. Save. Back in **Access controls → Applications**, click **Configure** on the application. Under **Additional settings**, copy the **Application Audience (AUD) Tag** into `CF_ACCESS_AUD`.
6. Put your team domain (**Zero Trust → Settings**) into `CF_ACCESS_TEAM_DOMAIN`.

### 3. Run

```sh
cp .env.example .env   # fill in PUBLIC_BASE_URL, CF_ACCESS_TEAM_DOMAIN, CF_ACCESS_AUD, TUNNEL_TOKEN
docker compose up -d --build
```

Open `https://recipes.example.com`. Access asks you to log in, and then the app opens.

## Connect Claude

1. On claude.ai, go to **Settings → Connectors → Add custom connector**.
2. Name it "Recipe Box". For the URL, use `https://recipes.example.com/mcp`. Leave the OAuth fields empty.
3. Click **Connect**. A Cloudflare Access login opens; log in with an allowed email.
4. The connector syncs to the Claude mobile app. In a chat, turn on the connector and say things like:
   - "Save this recipe to my recipe box."
   - "Make that dairy-free and update the saved one."
   - "Plan dinners for next week from my favorites, then give me the grocery list."

If Claude cannot finish the Access login, the likely cause is that Managed OAuth needs an OAuth client that supports RFC 8707. The fallback is to exclude `/mcp` from Access and protect it with a secret token in the URL instead. That needs a code change; the app refuses any request without an Access JWT.

## On your iPhone

- In Safari, tap **Share → Add to Home Screen** for an app-like icon.
- On a recipe, tap **Start cooking**. The bar at the bottom says "Screen stays on" while the wake lock is active. iOS 16.4 or later is required, and 18.4 or later for Home Screen apps.
- **Print** opens the one-page view and then the print dialog. **Share** on the grocery list sends the remaining items to Notes, Reminders, or Messages.

## Tools that Claude can use

| Tool | What it does |
| --- | --- |
| `save_recipe` | Saves a new recipe and returns its link. Ingredients have separate quantity, unit, and item fields. |
| `update_recipe` | Changes only the fields you send. |
| `get_recipe`, `search_recipes`, `list_categories` | Read. `search_recipes` can return only favorites. |
| `set_favorite` | Adds a recipe to favorites or removes it. |
| `create_meal_plan`, `add_to_meal_plan`, `remove_from_meal_plan` | Build a week. Removing an entry does not delete the recipe. |
| `list_meal_plans`, `get_meal_plan`, `get_grocery_list` | Read plans and the combined grocery list. |

## Data and backups

All data is in one SQLite file, `./data/recipes.db`: recipes, favorites, meal plans, and grocery check-offs.

Back it up with SQLite's backup API, run inside the container so it uses the same file locks as the app. This is safe while the app runs:

```sh
docker compose exec app python -c "import sqlite3; s=sqlite3.connect('/data/recipes.db'); d=sqlite3.connect('/data/backup-$(date +%F).db'); s.backup(d); d.close()"
```

Then copy `data/backup-<date>.db` somewhere safe. Do not copy `recipes.db` itself while the app runs: a copy taken during a write can be inconsistent.

To restore: `docker compose stop app`, replace `data/recipes.db` with the backup, then `docker compose start app`.

**Export all recipes (JSON)**, at the bottom of every page, downloads the recipes (not plans) in a readable form. Schema migrations run automatically at startup.

Keep a private copy of `.env` too, for example in a password manager. It is not data, but it holds your tunnel token and Access settings.

## Development

```sh
uv sync
uv run pytest
uvx ruff check app tests && uvx ruff format --check app tests

# Run locally with no authentication. Cooking mode works on localhost too.
DEV_NO_AUTH=true uv run uvicorn --factory app.main:create_app --reload
```

To test the MCP endpoint by hand, run `npx @modelcontextprotocol/inspector` and connect to `http://localhost:8000/mcp` with the Streamable HTTP transport (with `DEV_NO_AUTH=true`).

| Variable | Required | Meaning |
| --- | --- | --- |
| `PUBLIC_BASE_URL` | yes | Public URL, used in the links that Claude returns. Its host is also the only non-local Host header the MCP endpoint accepts. |
| `CF_ACCESS_TEAM_DOMAIN` | yes* | Your Zero Trust team domain, like `myteam.cloudflareaccess.com`. |
| `CF_ACCESS_AUD` | yes* | The Access application's AUD tag. |
| `ALLOWED_EMAILS` | no | Extra check after the Access policy. Comma separated. |
| `DEV_NO_AUTH` | no | `true` turns off authentication for local development. Cannot be combined with the `CF_ACCESS_*` settings. |
| `EXTRA_ALLOWED_HOSTS` | no | More Host headers for the MCP endpoint, comma separated. |
| `DATA_DIR` / `DB_PATH` | no | Where the database is. The container uses `/data`. |

\* Unless `DEV_NO_AUTH=true`.
