FROM rust:1.98-bookworm AS build
WORKDIR /src
COPY . .
RUN cargo build -p shop-api

FROM alpine:3.22
COPY --from=build /src/target/debug/shop-api /usr/local/bin/shop-api
EXPOSE 3000
CMD ["shop-api"]
