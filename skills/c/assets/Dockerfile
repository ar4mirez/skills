# syntax=docker/dockerfile:1
# Static musl build on Alpine, shipped on distroless/static (no shell, no libc,
# runs as uid 65532). Build: docker build -t kvstore .
FROM alpine:3.24 AS build
RUN apk add --no-cache build-base cmake samurai linux-headers
WORKDIR /src
COPY . .
RUN cmake --preset release -DKVSTORE_STATIC=ON \
 && cmake --build --preset release \
 && ctest --preset release \
 && strip build/release/kvstore-server

FROM gcr.io/distroless/static-debian13:nonroot
COPY --from=build /src/build/release/kvstore-server /usr/local/bin/kvstore-server
ENV PORT=8080
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/kvstore-server"]
