-- The database enforces the invariants; the app is not the only writer forever.
CREATE TABLE links (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug       TEXT UNIQUE CHECK (length(slug) BETWEEN 1 AND 64),
    url        TEXT NOT NULL CHECK (length(url) <= 2048),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
