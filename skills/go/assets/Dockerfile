# syntax=docker/dockerfile:1
# Static Go binary on distroless/static: no shell, no libc, no package manager, runs as nonroot.
# Build: docker build --build-arg VERSION=$(git rev-parse --short HEAD) -t links .

# Build on the host's native platform and cross-compile (fast; no QEMU emulation).
FROM --platform=$BUILDPLATFORM golang:1.27-trixie AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
ARG TARGETOS TARGETARCH VERSION=dev
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/links ./cmd/links

FROM gcr.io/distroless/static-debian13:nonroot
COPY --from=build /out/links /links
EXPOSE 8080
# No shell in the image: use exec form. `/links migrate` runs from the Kamal pre-deploy hook.
CMD ["/links", "serve"]
