"""Jinja environment and template filters."""

import hashlib
from itertools import groupby
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.ingredients import format_quantity

APP_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=APP_DIR / "templates")


def _asset_version() -> str:
    """Hash of the static files, so browsers fetch new CSS/JS after an upgrade."""
    digest = hashlib.sha256()
    for path in sorted((APP_DIR / "static").rglob("*")):
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def minutes(value: int | None) -> str:
    """95 -> '1 hr 35 min'."""
    if not value:
        return ""
    hours, mins = divmod(int(value), 60)
    if hours and mins:
        return f"{hours} hr {mins} min"
    return f"{hours} hr" if hours else f"{mins} min"


def sections(items: list) -> list[tuple[str | None, list]]:
    """Group consecutive ingredients or steps by their section heading."""
    return [(section, list(group)) for section, group in groupby(items, key=lambda i: i.section)]


templates.env.filters["minutes"] = minutes
templates.env.filters["sections"] = sections
templates.env.filters["qty"] = format_quantity
templates.env.globals["asset_version"] = _asset_version()
