# syntax=docker/dockerfile:1
# Build: docker build -t api --build-arg APP=@acme/api .
FROM node:24-trixie-slim AS build
ARG APP=@acme/api
WORKDIR /repo
RUN npm install --global pnpm@12.6.0
COPY . .
RUN pnpm install --frozen-lockfile \
 && pnpm --filter "${APP}^..." build \
 && pnpm --filter "${APP}" deploy --prod /out

# Node strips types natively (24.12+), so the service ships as .ts source: no build step.
FROM gcr.io/distroless/nodejs24-debian13:nonroot
WORKDIR /app
ENV NODE_ENV=production PORT=3000
COPY --from=build /out .
EXPOSE 3000
# The distroless entrypoint is already /nodejs/bin/node.
CMD ["src/server.ts"]
