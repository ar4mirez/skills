module github.com/acme/orders

go 1.21

require (
	github.com/gorilla/mux v1.8.1
	github.com/lib/pq v1.10.9
	github.com/pkg/errors v0.9.1
	github.com/sirupsen/logrus v1.9.3
)

replace github.com/acme/shared => ../shared
