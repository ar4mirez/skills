FROM oven/bun:1.4 AS build
WORKDIR /app
COPY . .
RUN bun install
RUN bun build --compile --bytecode --outfile server apps/api/src/index.ts

FROM alpine:3.20
COPY --from=build /app/server /server
CMD ["/server"]
