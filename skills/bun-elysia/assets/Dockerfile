# apps/api/Dockerfile: build from the monorepo root: docker build -f apps/api/Dockerfile .
# Stage 1: install + compile two standalone binaries (web + worker). No Bun needed at runtime.
FROM oven/bun:1.4 AS build
WORKDIR /repo

# Manifests first for layer caching (add every workspace the API depends on).
COPY package.json bun.lock bunfig.toml ./
COPY apps/api/package.json apps/api/
COPY packages/config/package.json packages/config/
COPY packages/db/package.json packages/db/
RUN bun install --frozen-lockfile --filter '@acme/api'

COPY apps/api apps/api
COPY packages packages
ENV NODE_ENV=production
WORKDIR /repo/apps/api
# --format=esm is required with --bytecode when code uses top-level await.
# glibc target → distroless/base. For Alpine use --target=bun-linux-x64-musl (or arm64-musl).
# Old CPUs without AVX2: --target=bun-linux-x64-baseline.
RUN bun build --compile --format=esm --minify-whitespace --minify-syntax --sourcemap --bytecode \
      --target=bun-linux-x64 --outfile dist/server src/index.ts \
 && bun build --compile --format=esm --minify-whitespace --minify-syntax --sourcemap --bytecode \
      --target=bun-linux-x64 --outfile dist/worker src/worker.ts

# Stage 2: minimal runtime, non-root.
FROM gcr.io/distroless/base-debian12:nonroot
WORKDIR /app
COPY --from=build /repo/apps/api/dist/server /repo/apps/api/dist/worker ./
COPY --from=build /repo/packages/db/migrations ./migrations
ENV NODE_ENV=production PORT=3000
EXPOSE 3000
CMD ["./server"]
