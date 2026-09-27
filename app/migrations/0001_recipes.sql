CREATE TABLE recipes (
    id            INTEGER PRIMARY KEY,
    slug          TEXT    NOT NULL UNIQUE,
    title         TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    category      TEXT    NOT NULL DEFAULT 'Uncategorized',
    cuisine       TEXT    NOT NULL DEFAULT '',
    tags          TEXT    NOT NULL DEFAULT '[]',   -- JSON list of strings
    servings      INTEGER,
    yield_text    TEXT    NOT NULL DEFAULT '',
    prep_minutes  INTEGER,
    cook_minutes  INTEGER,
    total_minutes INTEGER,
    ingredients   TEXT    NOT NULL DEFAULT '[]',   -- JSON list of Ingredient objects
    steps         TEXT    NOT NULL DEFAULT '[]',   -- JSON list of Step objects
    notes         TEXT    NOT NULL DEFAULT '',
    source        TEXT    NOT NULL DEFAULT '',
    source_url    TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);

CREATE INDEX recipes_category ON recipes (category);

-- Full-text index. rowid = recipes.id. Kept in sync by the triggers below.
CREATE VIRTUAL TABLE recipes_fts USING fts5 (
    title, description, category, tags, ingredients,
    tokenize = 'porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER recipes_fts_insert AFTER INSERT ON recipes BEGIN
    INSERT INTO recipes_fts (rowid, title, description, category, tags, ingredients)
    VALUES (
        new.id, new.title, new.description, new.category || ' ' || new.cuisine,
        (SELECT group_concat(value, ' ') FROM json_each(new.tags)),
        (SELECT group_concat(json_extract(value, '$.raw'), ' ') FROM json_each(new.ingredients))
    );
END;

CREATE TRIGGER recipes_fts_update AFTER UPDATE ON recipes BEGIN
    DELETE FROM recipes_fts WHERE rowid = old.id;
    INSERT INTO recipes_fts (rowid, title, description, category, tags, ingredients)
    VALUES (
        new.id, new.title, new.description, new.category || ' ' || new.cuisine,
        (SELECT group_concat(value, ' ') FROM json_each(new.tags)),
        (SELECT group_concat(json_extract(value, '$.raw'), ' ') FROM json_each(new.ingredients))
    );
END;

CREATE TRIGGER recipes_fts_delete AFTER DELETE ON recipes BEGIN
    DELETE FROM recipes_fts WHERE rowid = old.id;
END;
