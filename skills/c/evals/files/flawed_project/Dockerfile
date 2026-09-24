FROM gcc:15 AS build
WORKDIR /src
COPY . .
RUN cmake -S . -B build && cmake --build build

FROM ubuntu:24.04
COPY --from=build /src/build/confd /usr/local/bin/confd
CMD ["confd"]
