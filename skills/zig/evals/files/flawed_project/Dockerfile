FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y curl xz-utils
RUN curl -fsSL https://ziglang.org/download/0.13.0/zig-linux-x86_64-0.13.0.tar.xz | tar -xJ -C /opt
ENV PATH=/opt/zig-linux-x86_64-0.13.0:$PATH
WORKDIR /src
COPY . .
RUN zig build -Dtarget=x86_64-linux-gnu

FROM scratch
COPY --from=build /src/zig-out/bin/inventory /inventory
ENTRYPOINT ["/inventory"]
