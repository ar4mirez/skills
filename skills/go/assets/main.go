// Command links is the URL-shortener service. Subcommands:
//
//	links serve     run the HTTP server (default)
//	links migrate   apply database migrations, then exit
//	links version   print the build version
package main

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acme/links/db"
	"github.com/acme/links/internal/link"
	"github.com/acme/links/internal/server"
)

// version is set at build time: -ldflags "-X main.version=$VERSION".
var version = "dev"

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, os.Args[1:], os.Getenv, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "links:", err)
		os.Exit(1)
	}
}

// config is read once, at startup, from the environment.
type config struct {
	addr        string
	databaseURL string
	logLevel    slog.Level
}

func loadConfig(getenv func(string) string) (config, error) {
	cfg := config{addr: ":" + cmp.Or(getenv("PORT"), "8080"), databaseURL: getenv("DATABASE_URL")}
	if cfg.databaseURL == "" {
		return config{}, errors.New("DATABASE_URL is required")
	}
	if err := cfg.logLevel.UnmarshalText([]byte(cmp.Or(getenv("LOG_LEVEL"), "info"))); err != nil {
		return config{}, fmt.Errorf("LOG_LEVEL: %w", err)
	}
	return cfg, nil
}

// run is main without globals, so tests can call it with fake args and env.
func run(ctx context.Context, args []string, getenv func(string) string, stdout io.Writer) error {
	cmd := "serve"
	if len(args) > 0 {
		cmd = args[0]
	}
	if cmd == "version" {
		_, err := fmt.Fprintln(stdout, version)
		return err
	}
	if cmd != "serve" && cmd != "migrate" {
		return fmt.Errorf("unknown command %q (want serve, migrate, or version)", cmd)
	}

	cfg, err := loadConfig(getenv)
	if err != nil {
		return err
	}
	log := slog.New(slog.NewJSONHandler(stdout, &slog.HandlerOptions{Level: cfg.logLevel}))

	pool, err := pgxpool.New(ctx, cfg.databaseURL)
	if err != nil {
		return fmt.Errorf("connect database: %w", err)
	}
	defer pool.Close()

	if cmd == "migrate" {
		if err := db.Migrate(ctx, pool); err != nil {
			return err
		}
		log.Info("migrations applied")
		return nil
	}

	svc := link.NewService(link.NewPostgresStore(pool))
	handler := server.New(log, pool, link.NewHandler(svc, log))

	var lc net.ListenConfig
	ln, err := lc.Listen(ctx, "tcp", cfg.addr)
	if err != nil {
		return fmt.Errorf("listen %s: %w", cfg.addr, err)
	}
	return server.Serve(ctx, ln, handler, log, 8*time.Second) // under Docker's 10s stop timeout
}
