ALTER TABLE recipes ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0;

CREATE TABLE meal_plans (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    week_start  TEXT,             -- ISO date of the Monday, or NULL
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE meal_plan_items (
    id         INTEGER PRIMARY KEY,
    plan_id    INTEGER NOT NULL REFERENCES meal_plans (id) ON DELETE CASCADE,
    recipe_id  INTEGER NOT NULL REFERENCES recipes (id) ON DELETE CASCADE,
    day        INTEGER,           -- 0 = Monday ... 6 = Sunday, NULL = not scheduled
    servings   INTEGER,           -- NULL = the recipe's own servings
    created_at TEXT NOT NULL
);
CREATE INDEX meal_plan_items_plan ON meal_plan_items (plan_id);

CREATE TABLE grocery_checks (
    plan_id  INTEGER NOT NULL REFERENCES meal_plans (id) ON DELETE CASCADE,
    item_key TEXT    NOT NULL,
    PRIMARY KEY (plan_id, item_key)
);
