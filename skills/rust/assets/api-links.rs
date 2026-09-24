//! The links feature: routes, request/response types, and queries in one module.
use acme_core::{ShortCode, Slug};
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::Redirect;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};

use crate::AppState;
use crate::error::ApiError;

const MAX_URL_LEN: usize = 2048;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/links", post(create))
        .route("/links/{code}", get(show))
        .route("/r/{code}", get(follow))
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CreateLink {
    pub url: String,
    pub slug: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct LinkView {
    pub code: ShortCode,
    pub slug: Option<Slug>,
    pub url: String,
}

fn validate_url(url: &str) -> Result<(), ApiError> {
    if url.len() > MAX_URL_LEN {
        return Err(ApiError::Invalid(format!(
            "url longer than {MAX_URL_LEN} bytes"
        )));
    }
    if !(url.starts_with("https://") || url.starts_with("http://")) {
        return Err(ApiError::Invalid(
            "url must start with http:// or https://".into(),
        ));
    }
    Ok(())
}

/// Maps a decoded code to the database id. Codes beyond `i64::MAX` cannot exist.
fn db_id(code: &str) -> Result<i64, ApiError> {
    let code: ShortCode = code.parse().map_err(|_| ApiError::NotFound)?;
    i64::try_from(code.to_id()).map_err(|_| ApiError::NotFound)
}

fn code_for(id: i64) -> Result<ShortCode, ApiError> {
    let id = u64::try_from(id).map_err(|_| ApiError::Invalid("negative id".into()))?;
    Ok(ShortCode::from_id(id))
}

async fn create(
    State(state): State<AppState>,
    Json(input): Json<CreateLink>,
) -> Result<(StatusCode, Json<LinkView>), ApiError> {
    validate_url(&input.url)?;
    let slug = input.slug.as_deref().map(Slug::parse).transpose()?;

    // Compile-time checked against the migrated schema (DATABASE_URL, or .sqlx/ offline data).
    let row = sqlx::query!(
        "INSERT INTO links (slug, url) VALUES ($1, $2) RETURNING id",
        slug.as_ref().map(Slug::as_str),
        input.url,
    )
    .fetch_one(&state.db)
    .await
    .map_err(|err| match &err {
        sqlx::Error::Database(db) if db.is_unique_violation() => {
            ApiError::Conflict("slug already taken".into())
        }
        _ => ApiError::Database(err),
    })?;

    let view = LinkView {
        code: code_for(row.id)?,
        slug,
        url: input.url,
    };
    Ok((StatusCode::CREATED, Json(view)))
}

async fn show(
    State(state): State<AppState>,
    Path(code): Path<String>,
) -> Result<Json<LinkView>, ApiError> {
    let id = db_id(&code)?;
    let row = sqlx::query!("SELECT id, slug, url FROM links WHERE id = $1", id)
        .fetch_optional(&state.db)
        .await?
        .ok_or(ApiError::NotFound)?;
    Ok(Json(LinkView {
        code: code_for(row.id)?,
        slug: row.slug.as_deref().map(Slug::parse).transpose()?,
        url: row.url,
    }))
}

async fn follow(
    State(state): State<AppState>,
    Path(code): Path<String>,
) -> Result<Redirect, ApiError> {
    let id = db_id(&code)?;
    let url = sqlx::query_scalar!("SELECT url FROM links WHERE id = $1", id)
        .fetch_optional(&state.db)
        .await?
        .ok_or(ApiError::NotFound)?;
    Ok(Redirect::temporary(&url))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn url_rules() {
        assert!(validate_url("https://example.com").is_ok());
        assert!(validate_url("javascript:alert(1)").is_err());
        assert!(validate_url(&format!("https://{}", "a".repeat(MAX_URL_LEN))).is_err());
    }

    #[test]
    fn ids_out_of_range_are_not_found() {
        assert!(
            matches!(db_id("LygHa16AHYF"), Err(ApiError::NotFound)),
            "u64::MAX > i64::MAX"
        );
        assert!(matches!(db_id("not-a-code"), Err(ApiError::NotFound)));
        assert_eq!(db_id("21").unwrap(), 125);
    }
}
