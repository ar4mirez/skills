//! `cargo bench -p acme-core`. Criterion keeps history in target/criterion and reports regressions.
use std::hint::black_box;

use acme_core::{ShortCode, Slug};
use criterion::{Criterion, criterion_group, criterion_main};

fn codec(c: &mut Criterion) {
    c.bench_function("short_code_from_id", |b| {
        b.iter(|| ShortCode::from_id(black_box(9_876_543_210)));
    });
    c.bench_function("slug_parse", |b| {
        b.iter(|| Slug::parse(black_box("The Quick, Brown Fox -- Jumps!")));
    });
}

criterion_group!(benches, codec);
criterion_main!(benches);
