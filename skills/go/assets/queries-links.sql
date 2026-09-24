-- name: CreateLink :one
INSERT INTO links (code, target_url)
VALUES ($1, $2)
RETURNING id, code, target_url, created_at;

-- name: GetLinkByCode :one
SELECT id, code, target_url, created_at
FROM links
WHERE code = $1;

-- name: ListLinks :many
SELECT id, code, target_url, created_at
FROM links
ORDER BY id DESC
LIMIT $1;
