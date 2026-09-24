# syntax=docker/dockerfile:1
# Multi-stage: build with GCC 16 on Debian trixie, run on distroless/cc (trixie glibc).
# The binary links libstdc++/libgcc statically; glibc stays dynamic (see apps/wc-server).

FROM gcc:16-trixie AS build
ARG TARGETARCH
ARG CMAKE_VERSION=4.4.3
ARG VCPKG_COMMIT=9e593bb18ea69cc5095e012465dcd675a822ed0d
RUN apt-get update \
 && apt-get install -y --no-install-recommends ninja-build pkg-config curl zip unzip tar git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN case "$TARGETARCH" in amd64) a=x86_64 ;; arm64) a=aarch64 ;; *) echo "unsupported $TARGETARCH"; exit 1 ;; esac \
 && curl -fsSL "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION}/cmake-${CMAKE_VERSION}-linux-${a}.tar.gz" \
    | tar -xz --strip-components=1 -C /usr/local
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
