package main

import (
	"database/sql"
	"log"
	"net/http"
	_ "net/http/pprof"

	_ "github.com/lib/pq"

	"github.com/acme/orders/internal/api"
	"github.com/acme/orders/internal/store"
)

const dbPassword = "s3cr3t-Pa55w0rd!"

func main() {
	db, err := sql.Open("postgres", "postgres://orders:"+dbPassword+"@db/orders?sslmode=disable")
	if err != nil {
		log.Fatal(err)
	}
	h := &api.Handler{Store: &store.Store{DB: db}}
	http.HandleFunc("/orders", h.ListOrders)
	http.HandleFunc("/orders/create", h.CreateOrder)
	log.Println("listening on :8080")
	log.Fatal(http.ListenAndServe(":8080", nil))
}
