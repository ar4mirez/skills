//! HTTP-level tests against a real Postgres. `#[sqlx::test]` creates a fresh database per
//! test (from `DATABASE_URL`), applies `./migrations`, and drops it afterwards.
// clippy's allow-unwrap-in-tests covers #[test] bodies only, not helpers in tests/*.rs.
#![allow(
    clippy::unwrap_used,
    reason = "test helpers: a panic is the failure report"
)]
use std::time::Duration;

use acme_api::{AppState, app};
use axum::Router;
use axum::body::Body;
use axum::http::{Request, StatusCode, header};
use http_body_util::BodyExt;
use serde_json::{Value, json};
use sqlx::PgPool;
use tower::ServiceExt;

fn test_app(db: PgPool) -> Router {
    app(AppState { db }, Duration::from_secs(5))
}

async fn send(app: Router, req: Request<Body>) -> (StatusCode, Value) {
    let res = app.oneshot(req).await.unwrap();
    let status = res.status();
    let bytes = res.into_body().collect().await.unwrap().to_bytes();
    let body = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, body)
}

fn post_json(uri: &str, body: &Value) -> Request<Body> {
    Request::post(uri)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(body.to_string()))
        .unwrap()
}

#[sqlx::test]
async fn up_is_ok(db: PgPool) {
    let res = test_app(db)
        .oneshot(Request::get("/up").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert!(res.headers().contains_key("x-request-id"));
}

#[sqlx::test]
async fn create_show_and_follow(db: PgPool) {
    let (status, created) = send(
        test_app(db.clone()),
        post_json(
            "/links",
            &json!({ "url": "https://example.com/a", "slug": "My Link" }),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    assert_eq!(created["slug"], "my-link");
    let code = created["code"].as_str().unwrap().to_owned();

    let (status, shown) = send(
        test_app(db.clone()),
        Request::get(format!("/links/{code}"))
            .body(Body::empty())
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(shown, created);

    let res = test_app(db)
        .oneshot(
            Request::get(format!("/r/{code}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::TEMPORARY_REDIRECT);
    assert_eq!(res.headers()[header::LOCATION], "https://example.com/a");
}

#[sqlx::test]
async fn validation_conflict_and_not_found(db: PgPool) {
    let (status, _) = send(
        test_app(db.clone()),
        post_json("/links", &json!({ "url": "ftp://x" })),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);

    let body = json!({ "url": "https://example.com", "slug": "dup" });
    assert_eq!(
        send(test_app(db.clone()), post_json("/links", &body))
            .await
            .0,
        StatusCode::CREATED
    );
    let (status, err) = send(test_app(db.clone()), post_json("/links", &body)).await;
    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(err["error"], "conflict: slug already taken");

    let (status, _) = send(
        test_app(db),
        Request::get("/links/zzzz").body(Body::empty()).unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}
