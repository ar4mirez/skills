# syntax=docker/dockerfile:1
# Static Zig service image. Build: docker build -t tallyd .   (Kamal builds it for you.)
# The build stage runs on the builder's own arch and cross-compiles for TARGETARCH, so
# amd64 and arm64 images need no emulation.
FROM --platform=$BUILDPLATFORM debian:trixie-slim AS build
ARG TARGETARCH
ARG BUILDARCH
ARG ZIG_VERSION=0.16.0
# SHA-256 from https://ziglang.org/download/index.json (update with ZIG_VERSION).
ARG ZIG_SHA256_AMD64=70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00
ARG ZIG_SHA256_ARM64=ea4b09bfb22ec6f6c6ceac57ab63efb6b46e17ab08d21f69f3a48b38e1534f17
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl xz-utils \
 && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    case "$BUILDARCH" in \
      amd64) zarch=x86_64;  sum="$ZIG_SHA256_AMD64" ;; \
      arm64) zarch=aarch64; sum="$ZIG_SHA256_ARM64" ;; \
      *) echo "unsupported build arch: $BUILDARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /tmp/zig.tar.xz "https://ziglang.org/download/${ZIG_VERSION}/zig-${zarch}-linux-${ZIG_VERSION}.tar.xz"; \
    echo "${sum}  /tmp/zig.tar.xz" | sha256sum -c -; \
    mkdir /opt/zig && tar -xJf /tmp/zig.tar.xz -C /opt/zig --strip-components=1; \
    rm /tmp/zig.tar.xz
ENV PATH=/opt/zig:$PATH

WORKDIR /src
# Manifest first: dependency fetches are cached until build.zig.zon changes.
COPY build.zig build.zig.zon ./
RUN zig build --fetch
COPY src src
COPY include include
COPY examples examples
# ReleaseSafe keeps bounds/overflow checks on; musl gives a fully static binary.
RUN set -eu; \
    case "$TARGETARCH" in amd64) t=x86_64-linux-musl ;; arm64) t=aarch64-linux-musl ;; \
      *) echo "unsupported target arch: $TARGETARCH" >&2; exit 1 ;; esac; \
    zig build -Dtarget="$t" -Doptimize=ReleaseSafe -Dstrip=true

# Runtime: no shell, no package manager, non-root. CA certs and tzdata included.
# `FROM scratch` also works for a binary that makes no TLS calls (add USER 65532:65532).
FROM gcr.io/distroless/static-debian13:nonroot
COPY --from=build /src/zig-out/bin/tallyd /usr/local/bin/tallyd
ENV PORT=3000
EXPOSE 3000
USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/tallyd"]
