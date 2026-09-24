//go:build ignore

// Command scaffold lays the skill's verified templates out as a new Go
// module: a network service (default) or a library. Only the module path is
// rewritten; everything else is the exact code that was built and tested.
//
// Usage:
//
//	go run scripts/scaffold.go --module github.com/you/app [--kind service|library] [--assets DIR] DIR
//
// After scaffolding a service: rename cmd/links and the "links" names in
// Dockerfile, config/deploy.yml, and .kamal/hooks/pre-deploy to your binary
// name, then run go mod tidy && go vet ./... && go test -race ./... .
//
// Exit codes: 0 = scaffolded, 1 = DIR exists and is not empty (or a write
// failed), 2 = bad input.
package main

import (
	"errors"
	"flag"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
)

// service maps asset file -> destination path in the new module.
var service = map[string]string{
	"go.mod.tmpl":            "go.mod",
	"go.sum.tmpl":            "go.sum",
	"main.go":                "cmd/links/main.go",
	"main_test.go":           "cmd/links/main_test.go",
	"server.go":              "internal/server/server.go",
	"server_test.go":         "internal/server/server_test.go",
	"link.go":                "internal/link/link.go",
	"link_test.go":           "internal/link/link_test.go",
	"http.go":                "internal/link/http.go",
	"http_test.go":           "internal/link/http_test.go",
	"postgres.go":            "internal/link/postgres.go",
	"postgres_test.go":       "internal/link/postgres_test.go",
	"fake_test.go":           "internal/link/fake_test.go",
	"linkdb-db.go":           "internal/link/linkdb/db.go",
	"linkdb-models.go":       "internal/link/linkdb/models.go",
	"linkdb-links.sql.go":    "internal/link/linkdb/links.sql.go",
	"db.go":                  "db/db.go",
	"00001_create_links.sql": "db/migrations/00001_create_links.sql",
	"queries-links.sql":      "db/queries/links.sql",
	"sqlc.yaml":              "sqlc.yaml",
	"golangci.yml":           ".golangci.yml",
	"Dockerfile":             "Dockerfile",
	"dockerignore":           ".dockerignore",
	"deploy.yml":             "config/deploy.yml",
	"kamal-pre-deploy":       ".kamal/hooks/pre-deploy",
	"github-ci.yml":          ".github/workflows/ci.yml",
}

var library = map[string]string{
	"retry.go":              "retry.go",
	"retry_test.go":         "retry_test.go",
	"retry_example_test.go": "example_test.go",
	"golangci.yml":          ".golangci.yml",
}

const (
	serviceModule = "github.com/acme/links"
	libraryModule = "github.com/acme/retry"
)

var modulePath = regexp.MustCompile(`^[a-z0-9][a-z0-9.-]*(/[A-Za-z0-9._~-]+)+$|^[a-z][a-z0-9_-]*$`)

func main() {
	os.Exit(run(os.Args[1:]))
}

func run(args []string) int {
	fl := flag.NewFlagSet("scaffold", flag.ContinueOnError)
	fl.SetOutput(os.Stderr)
	module := fl.String("module", "", "module path for go.mod (required), e.g. github.com/you/app")
	kind := fl.String("kind", "service", "what to scaffold: service or library")
	assets := fl.String("assets", "", "assets directory (default: ../assets next to this script)")
	fl.Usage = func() {
		fmt.Fprint(fl.Output(), "Usage: go run scripts/scaffold.go --module PATH [--kind service|library] [--assets DIR] DIR\n\n"+
			"Creates a new Go module in DIR from the skill's verified templates.\n"+
			"Exit codes: 0 = scaffolded, 1 = DIR not empty or write failed, 2 = bad input.\n\n")
		fl.PrintDefaults()
	}
	if err := fl.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return 0
		}
		return 2
	}
	if fl.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "Error: exactly one target DIR is required")
		fl.Usage()
		return 2
	}
	if !modulePath.MatchString(*module) {
		fmt.Fprintf(os.Stderr, "Error: --module %q is not a valid module path (e.g. github.com/you/app)\n", *module)
		return 2
	}
	var files map[string]string
	switch *kind {
	case "service":
		files = service
	case "library":
		files = library
	default:
		fmt.Fprintf(os.Stderr, "Error: --kind must be service or library (got %q)\n", *kind)
		return 2
	}
	src, err := assetsDir(*assets)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		return 2
	}
	dst := fl.Arg(0)
	if entries, err := os.ReadDir(dst); err == nil && len(entries) > 0 {
		fmt.Fprintf(os.Stderr, "Error: %s exists and is not empty\n", dst)
		return 1
	}

	for asset, rel := range files {
		data, err := os.ReadFile(filepath.Join(src, asset))
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error: missing asset:", err)
			return 2
		}
		text := strings.ReplaceAll(string(data), serviceModule, *module)
		text = strings.ReplaceAll(text, libraryModule, *module)
		mode := fs.FileMode(0o644)
		if strings.Contains(rel, "hooks/") {
			mode = 0o755
		}
		if err := write(filepath.Join(dst, rel), text, mode); err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			return 1
		}
	}
	if *kind == "library" {
		if err := write(filepath.Join(dst, "go.mod"), "module "+*module+"\n\ngo 1.27.0\n", 0o644); err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			return 1
		}
	}
	fmt.Printf("Scaffolded a %s (%d files) in %s with module %s.\n", *kind, len(files), dst, *module)
	fmt.Println("Next: go mod tidy && go vet ./... && go test -race ./...")
	return 0
}

func write(path, text string, mode fs.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, []byte(text), mode)
}

// assetsDir finds the skill's assets: the flag, then next to this source
// file, then relative to the working directory.
func assetsDir(flagValue string) (string, error) {
	candidates := []string{flagValue}
	if _, file, _, ok := runtime.Caller(0); ok && filepath.IsAbs(file) {
		candidates = append(candidates, filepath.Join(filepath.Dir(file), "..", "assets"))
	}
	candidates = append(candidates, "assets", filepath.Join("..", "assets"))
	for _, c := range candidates {
		if c == "" {
			continue
		}
		if _, err := os.Stat(filepath.Join(c, "retry.go")); err == nil {
			return c, nil
		}
	}
	return "", errors.New("cannot find the skill's assets directory; pass --assets")
}
