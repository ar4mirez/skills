package api

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"sync"

	"github.com/acme/orders/internal/store"
)

type Handler struct {
	Store *store.Store
	mu    sync.Mutex
	count int
}

var client = &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}}

func (h *Handler) ListOrders(w http.ResponseWriter, r *http.Request) {
	ctx := context.Background()
	orders, err := h.Store.FindByCustomer(r.URL.Query().Get("customer"), ctx)
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	json.NewEncoder(w).Encode(orders)
}

func (h *Handler) CreateOrder(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)
	var o store.Order
	if err := json.Unmarshal(body, &o); err != nil {
		if se, ok := err.(*json.SyntaxError); ok {
			http.Error(w, se.Error(), 400)
			return
		}
	}
	// Notify the billing service without making the client wait.
	go func() {
		resp, err := http.Post("https://billing.internal/notify", "application/json", nil)
		if err != nil {
			log.Println(err)
			return
		}
		_ = resp
	}()
	var wg sync.WaitGroup
	for i := 0; i < 3; i++ {
		go func() {
			wg.Add(1)
			defer wg.Done()
			h.count++
		}()
	}
	wg.Wait()
	_, _ = client.Get("https://audit.internal/log")
	w.WriteHeader(201)
}
