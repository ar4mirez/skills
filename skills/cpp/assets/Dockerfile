# syntax=docker/dockerfile:1
# Multi-stage: build with GCC 16 on Debian trixie, run on distroless/cc (trixie glibc).
# The binary links libstdc++/libgcc statically; glibc stays dynamic (see apps/wc-server).

FROM gcc:16-trixie AS build
ARG TARGETARCH
ARG CMAKE_VERSION=4.4.3
# SHA-256 from the release's cmake-${CMAKE_VERSION}-SHA-256.txt (update with CMAKE_VERSION).
ARG CMAKE_SHA256_AMD64=d6c83076c575bc00b823522ac974bda66d0af05d6ddc30e739c12385cf32c6cc
ARG CMAKE_SHA256_ARM64=2efc974dbd63b4444c0e8494b92f2e80c2d7e635b4b80eac2916985ddd8f72a6
ARG VCPKG_COMMIT=9e593bb18ea69cc5095e012465dcd675a822ed0d
RUN apt-get update \
 && apt-get install -y --no-install-recommends ninja-build pkg-config curl zip unzip tar git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) a=x86_64;  sum="$CMAKE_SHA256_AMD64" ;; \
      arm64) a=aarch64; sum="$CMAKE_SHA256_ARM64" ;; \
      *) echo "unsupported $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /tmp/cmake.tar.gz "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION}/cmake-${CMAKE_VERSION}-linux-${a}.tar.gz"; \
    echo "${sum}  /tmp/cmake.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/cmake.tar.gz --strip-components=1 -C /usr/local; \
    rm /tmp/cmake.tar.gz
ENV VCPKG_ROOT=/opt/vcpkg
RUN git clone https://github.com/microsoft/vcpkg "$VCPKG_ROOT" \
 && git -C "$VCPKG_ROOT" checkout "$VCPKG_COMMIT" \
 && "$VCPKG_ROOT/bootstrap-vcpkg.sh" -disableMetrics

WORKDIR /src
COPY . .
# vcpkg installs during `cmake --preset`; the cache mount keeps its binary
# archives between builds so dependencies aren't rebuilt on every source edit.
RUN --mount=type=cache,target=/root/.cache/vcpkg \
    cmake --preset release \
 && cmake --build --preset release --target acme_wc_server \
 && strip build/release/apps/wc-server/wc-server

FROM gcr.io/distroless/cc-debian13:nonroot
COPY --from=build /src/build/release/apps/wc-server/wc-server /usr/local/bin/wc-server
ENV PORT=8080
EXPOSE 8080
USER nonroot
ENTRYPOINT ["/usr/local/bin/wc-server"]
