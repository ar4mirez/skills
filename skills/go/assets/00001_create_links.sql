-- +goose Up
CREATE TABLE links (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code       text        NOT NULL UNIQUE CHECK (length(code) BETWEEN 4 AND 32),
    target_url text        NOT NULL CHECK (length(target_url) <= 2048),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- +goose Down
DROP TABLE links;
