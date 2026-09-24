FROM golang:1.21 AS build
WORKDIR /src
COPY . .
RUN go build -o /orders .

FROM scratch
COPY --from=build /orders /orders
ENTRYPOINT ["/orders"]
