package link

import (
	"errors"
	"log/slog"
	"net/http"
	"strconv"

	"encoding/json/v2"
)

const maxBodyBytes = 1 << 20 // 1 MiB

// Handler exposes the Service over HTTP. It only translates: decode,
// call the service, map errors to status codes, encode.
type Handler struct {
	svc *Service
	log *slog.Logger
}

// NewHandler returns a Handler for svc.
func NewHandler(svc *Service, log *slog.Logger) *Handler {
	return &Handler{svc: svc, log: log}
}

// Register mounts the routes with Go 1.22+ method and wildcard patterns.
func (h *Handler) Register(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/links", h.create)
	mux.HandleFunc("GET /api/links", h.list)
	mux.HandleFunc("GET /{code}", h.redirect)
}

type createRequest struct {
	URL  string `json:"url"`
	Code string `json:"code,omitzero"`
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request) {
	var req createRequest
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	if err := json.UnmarshalRead(r.Body, &req, json.RejectUnknownMembers(true)); err != nil {
		if _, tooBig := errors.AsType[*http.MaxBytesError](err); tooBig {
			h.writeJSON(w, http.StatusRequestEntityTooLarge, errorBody{Error: "request body too large"})
			return
		}
		h.writeJSON(w, http.StatusBadRequest, errorBody{Error: "invalid JSON body"})
		return
	}
	l, err := h.svc.Shorten(r.Context(), req.URL, req.Code)
	if err != nil {
		h.writeError(w, r, err)
		return
	}
	h.writeJSON(w, http.StatusCreated, l)
}

func (h *Handler) list(w http.ResponseWriter, r *http.Request) {
	limit := 20
	if s := r.URL.Query().Get("limit"); s != "" {
		n, err := strconv.Atoi(s)
		if err != nil {
			h.writeError(w, r, &ValidationError{Field: "limit", Reason: "must be an integer"})
			return
		}
		limit = n
	}
	links, err := h.svc.Recent(r.Context(), limit)
	if err != nil {
		h.writeError(w, r, err)
		return
	}
	h.writeJSON(w, http.StatusOK, map[string][]Link{"links": links})
}

func (h *Handler) redirect(w http.ResponseWriter, r *http.Request) {
	l, err := h.svc.Resolve(r.Context(), r.PathValue("code"))
	if err != nil {
		h.writeError(w, r, err)
		return
	}
	http.Redirect(w, r, l.TargetURL, http.StatusFound)
}

type errorBody struct {
	Error string `json:"error"`
	Field string `json:"field,omitzero"`
}

// writeError maps domain errors to status codes. Unknown errors are logged
// with the request context and never leaked to the client.
func (h *Handler) writeError(w http.ResponseWriter, r *http.Request, err error) {
	if ve, ok := errors.AsType[*ValidationError](err); ok {
		h.writeJSON(w, http.StatusUnprocessableEntity, errorBody{Error: ve.Reason, Field: ve.Field})
		return
	}
	switch {
	case errors.Is(err, ErrNotFound):
		h.writeJSON(w, http.StatusNotFound, errorBody{Error: "not found"})
	case errors.Is(err, ErrCodeTaken):
		h.writeJSON(w, http.StatusConflict, errorBody{Error: "code already taken"})
	default:
		h.log.ErrorContext(r.Context(), "request failed", "method", r.Method, "path", r.URL.Path, "err", err)
		h.writeJSON(w, http.StatusInternalServerError, errorBody{Error: "internal error"})
	}
}

func (h *Handler) writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.MarshalWrite(w, v); err != nil {
		h.log.Error("encode response", "err", err)
	}
}
