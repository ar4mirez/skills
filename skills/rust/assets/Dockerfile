# Dockerfile for acme-api. Build from the workspace root: docker build -t acme-api .
# cargo-chef caches the dependency build in its own layer, so code-only changes
# rebuild in seconds instead of recompiling every crate.
FROM lukemathwalker/cargo-chef:0.1.78-rust-1.98.1-slim-trixie AS chef
WORKDIR /app
# Use the image's toolchain as-is; rust-toolchain.toml would otherwise make rustup
# fetch rustfmt/clippy during the build. Keep this tag in sync with the toolchain pin.
ENV RUSTUP_TOOLCHAIN=1.98.1

FROM chef AS planner
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

FROM chef AS builder
COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --locked --recipe-path recipe.json
COPY . .
# Queries were checked at dev time; .sqlx/ lets the image build without a database.
ENV SQLX_OFFLINE=true
RUN cargo build --release --locked -p acme-api

# glibc runtime (distroless/cc has libc, libgcc, ca-certificates, tzdata), non-root.
# Fully static musl alternative: build --target x86_64-unknown-linux-musl and use
# gcr.io/distroless/static-debian13:nonroot; musl's allocator is slow under contention, so
# pair it with a global allocator such as mimalloc.
FROM gcr.io/distroless/cc-debian13:nonroot
COPY --from=builder /app/target/release/acme-api /usr/local/bin/acme-api
ENV PORT=3000 RUST_LOG=info
EXPOSE 3000
ENTRYPOINT ["/usr/local/bin/acme-api"]
