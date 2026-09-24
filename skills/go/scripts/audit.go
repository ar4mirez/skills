//go:build ignore

// Command audit is a static health check of a Go project. No network, no
// build, no dependencies beyond the standard library.
//
// Usage:
//
//	go run scripts/audit.go [ROOT] [--json] [--fail-on high|medium|low|none]
//
// High: SQL built with fmt.Sprintf or + and passed to Query/Exec; http.Server
// without ReadHeaderTimeout, or package-level http.ListenAndServe;
// InsecureSkipVerify: true; hard-coded secrets; a binary built without
// CGO_ENABLED=0 copied into a scratch or distroless-static image.
//
// Medium: errors formatted with %v/%s instead of %w; == on sentinel errors;
// type assertions on errors; context.Background/TODO inside HTTP handlers;
// context stored in structs; panic, log.Fatal, or os.Exit outside package main;
// the default HTTP client, a client without Timeout, or DefaultServeMux;
// net/http/pprof blank imports; request bodies read without
// http.MaxBytesReader; defer inside a loop; ListenAndServe with no Shutdown;
// local replace directives; missing go.sum; the golang image as the final stage.
//
// Low: context.Context not the first parameter; GetX getters;
// util/common/helpers packages; a top-level pkg/ dir; tools.go instead of the
// tool directive; io/ioutil; pkg/errors, logrus, lib/pq, router frameworks;
// an unsupported go directive; time.Sleep in tests; go test without -race in
// CI; go build without -trimpath in a Dockerfile.
//
// Exit codes: 0 = no findings at or above --fail-on (default: high),
// 1 = findings, 2 = bad input.
package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
)

type finding struct {
	Severity string `json:"severity"`
	Check    string `json:"check"`
	Location string `json:"location"`
	Message  string `json:"message"`
}

var severities = []string{"high", "medium", "low"}

var skipDirs = map[string]bool{".git": true, "vendor": true, "testdata": true, "node_modules": true, "dist": true, "bin": true}

const usage = `Usage: go run scripts/audit.go [ROOT] [--json] [--fail-on high|medium|low|none]

Static health check of a Go project: security, error handling, context use,
HTTP servers, layout, go.mod hygiene, Dockerfiles, and CI workflows.

Examples:
  go run scripts/audit.go .
  go run scripts/audit.go ~/code/svc --json --fail-on medium

Exit codes: 0 = no findings at or above --fail-on (default high), 1 = findings, 2 = bad input.
`

type auditor struct {
	root     string
	fset     *token.FileSet
	findings []finding
	// module-wide facts for cross-file checks
	listenAndServe []string
	hasShutdown    bool
}

func (a *auditor) add(sev, check, loc, msg string) {
	a.findings = append(a.findings, finding{sev, check, loc, msg})
}

func (a *auditor) rel(p string) string {
	r, err := filepath.Rel(a.root, p)
	if err != nil {
		return p
	}
	return filepath.ToSlash(r)
}

func (a *auditor) pos(p token.Pos) string {
	ps := a.fset.Position(p)
	return fmt.Sprintf("%s:%d", a.rel(ps.Filename), ps.Line)
}

func main() {
	os.Exit(run(os.Args[1:]))
}

func run(args []string) int {
	root, asJSON, failOn := ".", false, "high"
	rootSet := false
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch {
		case arg == "-h" || arg == "--help":
			fmt.Print(usage)
			return 0
		case arg == "--json":
			asJSON = true
		case arg == "--fail-on":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, "Error: --fail-on needs a value")
				return 2
			}
			i++
			failOn = args[i]
		case strings.HasPrefix(arg, "--fail-on="):
			failOn = strings.TrimPrefix(arg, "--fail-on=")
		case strings.HasPrefix(arg, "-"):
			fmt.Fprintf(os.Stderr, "Error: unknown flag %q\n\n%s", arg, usage)
			return 2
		default:
			if rootSet {
				fmt.Fprintf(os.Stderr, "Error: more than one ROOT given\n\n%s", usage)
				return 2
			}
			root, rootSet = arg, true
		}
	}
	threshold := slices.Index(severities, failOn)
	if threshold < 0 && failOn != "none" {
		fmt.Fprintf(os.Stderr, "Error: --fail-on must be one of high, medium, low, none (got %q)\n", failOn)
		return 2
	}
	abs, err := filepath.Abs(root)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		return 2
	}
	if st, err := os.Stat(abs); err != nil || !st.IsDir() {
		fmt.Fprintf(os.Stderr, "Error: %q is not a directory\n", root)
		return 2
	}

	a := &auditor{root: abs, fset: token.NewFileSet()}
	goFiles, other := a.collect()
	if len(goFiles) == 0 && !slices.ContainsFunc(other, func(p string) bool { return filepath.Base(p) == "go.mod" }) {
		fmt.Fprintf(os.Stderr, "Error: %q has no go.mod or .go files. Pass the project root.\n", root)
		return 2
	}
	for _, f := range goFiles {
		a.checkGoFile(f)
	}
	for _, f := range other {
		a.checkOtherFile(f)
	}
	a.checkLayout()
	if len(a.listenAndServe) > 0 && !a.hasShutdown {
		a.add("medium", "no-graceful-shutdown", a.listenAndServe[0],
			"The server never calls Shutdown. Catch SIGTERM with signal.NotifyContext and call srv.Shutdown(ctx) so deploys drain in-flight requests.")
	}
	slices.SortStableFunc(a.findings, func(x, y finding) int {
		if d := slices.Index(severities, x.Severity) - slices.Index(severities, y.Severity); d != 0 {
			return d
		}
		return strings.Compare(x.Location, y.Location)
	})

	if asJSON {
		out := struct {
			Root     string    `json:"root"`
			Findings []finding `json:"findings"`
		}{abs, a.findings}
		if out.Findings == nil {
			out.Findings = []finding{}
		}
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(out)
	} else {
		printReport(a.findings)
	}
	if failOn == "none" {
		return 0
	}
	for _, f := range a.findings {
		if slices.Index(severities, f.Severity) <= threshold {
			return 1
		}
	}
	return 0
}

func printReport(fs []finding) {
	if len(fs) == 0 {
		fmt.Println("No findings.")
	}
	for _, sev := range severities {
		first := true
		for _, f := range fs {
			if f.Severity != sev {
				continue
			}
			if first {
				fmt.Printf("\n%s\n", strings.ToUpper(sev))
				first = false
			}
			fmt.Printf("  [%s] %s\n      %s\n", f.Check, f.Location, f.Message)
		}
	}
	counts := make([]string, 0, len(severities))
	for _, sev := range severities {
		n := 0
		for _, f := range fs {
			if f.Severity == sev {
				n++
			}
		}
		counts = append(counts, fmt.Sprintf("%d %s", n, sev))
	}
	fmt.Printf("\nSummary: %s\n", strings.Join(counts, ", "))
}

func (a *auditor) collect() (goFiles, other []string) {
	_ = filepath.WalkDir(a.root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			if p != a.root && (skipDirs[d.Name()] || strings.HasPrefix(d.Name(), ".") && d.Name() != ".github") {
				return filepath.SkipDir
			}
			return nil
		}
		name := d.Name()
		switch {
		case strings.HasSuffix(name, ".go"):
			goFiles = append(goFiles, p)
		case name == "go.mod" || name == "Dockerfile" || strings.HasSuffix(name, ".Dockerfile") || strings.HasPrefix(name, "Dockerfile."):
			other = append(other, p)
		case (strings.HasSuffix(name, ".yml") || strings.HasSuffix(name, ".yaml")) && strings.Contains(filepath.ToSlash(p), ".github/workflows/"):
			other = append(other, p)
		}
		return nil
	})
	return goFiles, other
}

// ---------- Go source checks ----------

var (
	sqlVerb     = regexp.MustCompile(`(?i)^\s*(select|insert|update|delete|with|create|drop|alter)\b`)
	sqlFormat   = regexp.MustCompile(`(?is)^\s*(select|insert|update|delete)\b.*\b(from|into|set|where)\b.*%[-+# 0-9.]*[sdvq]`)
	secretName  = regexp.MustCompile(`(?i)(password|passwd|secret|api_?key|access_?key|private_?key|auth_?token|token)$`)
	utilPackage = map[string]bool{"util": true, "utils": true, "common": true, "helpers": true, "helper": true, "misc": true, "shared": true}
	queryFuncs  = map[string]bool{"Query": true, "QueryRow": true, "QueryContext": true, "QueryRowContext": true, "Exec": true, "ExecContext": true, "Prepare": true, "PrepareContext": true, "Select": true, "Get": true}
	sentinelErr = regexp.MustCompile(`^Err[A-Z]\w*$`) // io.EOF from Read is returned unwrapped by contract
)

func (a *auditor) checkGoFile(path string) {
	src, err := os.ReadFile(path)
	if err != nil {
		return
	}
	f, err := parser.ParseFile(a.fset, path, src, parser.ParseComments|parser.SkipObjectResolution)
	if err != nil {
		a.add("low", "parse-error", a.rel(path), "Could not parse: "+firstLine(err.Error()))
		return
	}
	if ast.IsGenerated(f) {
		return
	}
	isTest := strings.HasSuffix(path, "_test.go")
	pkg := f.Name.Name
	isMain := pkg == "main"
	imports := map[string]string{} // local name -> path
	for _, imp := range f.Imports {
		p, _ := strconv.Unquote(imp.Path.Value)
		name := p[strings.LastIndex(p, "/")+1:]
		if strings.HasPrefix(name, "v") && len(name) <= 3 && strings.Contains(p, "/") { // math/rand/v2, json/v2
			q := strings.TrimSuffix(p, "/"+name)
			name = q[strings.LastIndex(q, "/")+1:]
		}
		if imp.Name != nil {
			name = imp.Name.Name
		}
		imports[name] = p
		switch {
		case p == "io/ioutil":
			a.add("low", "ioutil", a.pos(imp.Pos()), "io/ioutil is deprecated. Use io.ReadAll, os.ReadFile, os.WriteFile, os.MkdirTemp.")
		case p == "net/http/pprof" && imp.Name != nil && imp.Name.Name == "_":
			a.add("medium", "pprof-default-mux", a.pos(imp.Pos()), "Blank-importing net/http/pprof registers /debug/pprof on DefaultServeMux. Mount pprof handlers on a separate, private listener instead.")
		case p == "github.com/pkg/errors":
			a.add("low", "pkg-errors", a.pos(imp.Pos()), "github.com/pkg/errors is archived. Use fmt.Errorf with %w and errors.Is/As/AsType.")
		}
	}
	if utilPackage[pkg] && !isTest {
		a.add("low", "util-package", a.rel(path), fmt.Sprintf("Package %q says nothing about what it provides. Move each helper next to its caller or into a package named for its purpose.", pkg))
	}
	hasMaxBytes := strings.Contains(string(src), "MaxBytesReader")

	// Function-scoped checks.
	for _, decl := range f.Decls {
		switch d := decl.(type) {
		case *ast.FuncDecl:
			a.checkFunc(d, isTest, isMain, imports, hasMaxBytes)
		case *ast.GenDecl:
			a.checkGenDecl(d, isTest)
		}
	}

	// Expression-level checks over the whole file.
	ast.Inspect(f, func(n ast.Node) bool {
		switch x := n.(type) {
		case *ast.CallExpr:
			a.checkCall(x, isTest, isMain, imports)
		case *ast.CompositeLit:
			a.checkCompositeLit(x, imports)
		case *ast.KeyValueExpr:
			if !isTest {
				a.checkSecret(identName(x.Key), x.Value)
			}
			if id, ok := x.Key.(*ast.Ident); ok && id.Name == "InsecureSkipVerify" {
				if v, ok := x.Value.(*ast.Ident); ok && v.Name == "true" && !isTest {
					a.add("high", "insecure-skip-verify", a.pos(x.Pos()), "InsecureSkipVerify: true disables TLS certificate checks (MITM). Configure RootCAs instead.")
				}
			}
		case *ast.AssignStmt:
			if !isTest && len(x.Lhs) == len(x.Rhs) {
				for i, lhs := range x.Lhs {
					a.checkSecret(identName(lhs), x.Rhs[i])
				}
			}
		case *ast.BinaryExpr:
			if x.Op == token.EQL || x.Op == token.NEQ {
				a.checkErrCompare(x)
			}
		case *ast.TypeAssertExpr:
			if id, ok := x.X.(*ast.Ident); ok && id.Name == "err" && x.Type != nil {
				a.add("medium", "error-type-assertion", a.pos(x.Pos()), "Type-asserting err misses wrapped errors. Use errors.AsType[*T](err) (Go 1.26+) or errors.As.")
			}
		case *ast.TypeSwitchStmt:
			if as, ok := x.Assign.(*ast.AssignStmt); ok && len(as.Rhs) == 1 {
				if ta, ok := as.Rhs[0].(*ast.TypeAssertExpr); ok {
					if id, ok := ta.X.(*ast.Ident); ok && id.Name == "err" {
						a.add("medium", "error-type-assertion", a.pos(x.Pos()), "A type switch on err misses wrapped errors. Use errors.AsType[*T](err) or errors.As per type.")
					}
				}
			}
		case *ast.StructType:
			for _, fld := range x.Fields.List {
				if isSelector(fld.Type, imports, "context", "Context") {
					a.add("medium", "context-in-struct", a.pos(fld.Pos()), "Don't store a context.Context in a struct. Pass ctx as the first parameter of each call.")
				}
			}
		}
		return true
	})
}

func (a *auditor) checkGenDecl(d *ast.GenDecl, isTest bool) {
	if isTest || (d.Tok != token.VAR && d.Tok != token.CONST) {
		return
	}
	for _, spec := range d.Specs {
		vs, ok := spec.(*ast.ValueSpec)
		if !ok {
			continue
		}
		for i, name := range vs.Names {
			if i < len(vs.Values) {
				a.checkSecret(name.Name, vs.Values[i])
			}
		}
	}
}

func (a *auditor) checkSecret(name string, val ast.Expr) {
	lit, ok := val.(*ast.BasicLit)
	if !ok || lit.Kind != token.STRING || !secretName.MatchString(name) {
		return
	}
	s, _ := strconv.Unquote(lit.Value)
	// Real secrets mix character classes; "password" or "api_key" are labels, not secrets.
	if len(s) < 8 || strings.ContainsAny(s, " {}$<>") || !strings.ContainsAny(s, "0123456789!@#%^&*+=/") {
		return
	}
	a.add("high", "hardcoded-secret", a.pos(lit.Pos()), fmt.Sprintf("%s looks like a hard-coded secret. Read it from the environment (or a secret manager) at startup.", name))
}

func (a *auditor) checkFunc(d *ast.FuncDecl, isTest, isMain bool, imports map[string]string, hasMaxBytes bool) {
	// context.Context should be the first parameter.
	if d.Type.Params != nil {
		idx := 0
		for _, fld := range d.Type.Params.List {
			n := max(len(fld.Names), 1)
			if isSelector(fld.Type, imports, "context", "Context") && idx > 0 {
				a.add("low", "context-not-first", a.pos(fld.Pos()), fmt.Sprintf("%s: context.Context should be the first parameter, named ctx.", d.Name.Name))
			}
			idx += n
		}
	}
	// GetX() getters.
	if d.Recv != nil && strings.HasPrefix(d.Name.Name, "Get") && len(d.Name.Name) > 3 && ast.IsExported(d.Name.Name) &&
		(d.Type.Params == nil || len(d.Type.Params.List) == 0) && d.Type.Results != nil && len(d.Type.Results.List) == 1 {
		a.add("low", "getter-prefix", a.pos(d.Pos()), fmt.Sprintf("Go getters drop the Get prefix: %s() instead of %s().", strings.TrimPrefix(d.Name.Name, "Get"), d.Name.Name))
	}
	if d.Body == nil {
		return
	}
	isHandler := hasParamType(d.Type, imports, "net/http", "ResponseWriter")
	if !isTest && !isMain && d.Name.Name != "init" && !strings.HasPrefix(d.Name.Name, "Must") && !strings.HasPrefix(d.Name.Name, "must") {
		ast.Inspect(d.Body, func(n ast.Node) bool {
			if _, ok := n.(*ast.FuncLit); ok {
				return true
			}
			if c, ok := n.(*ast.CallExpr); ok {
				if id, ok := c.Fun.(*ast.Ident); ok && id.Name == "panic" {
					if !isRePanic(c) {
						a.add("medium", "panic-in-library", a.pos(c.Pos()), fmt.Sprintf("%s panics. Return an error; panic only for programmer bugs (or in a Must* helper).", d.Name.Name))
					}
				}
			}
			return true
		})
	}
	a.walkFuncBody(d.Body, isTest, isHandler, imports, hasMaxBytes)
}

// isRePanic reports panic(v) inside a recover block, e.g. re-panicking http.ErrAbortHandler.
func isRePanic(c *ast.CallExpr) bool {
	if len(c.Args) != 1 {
		return false
	}
	switch x := c.Args[0].(type) {
	case *ast.Ident:
		return x.Name == "v" || x.Name == "r" || x.Name == "p" || x.Name == "rec"
	case *ast.SelectorExpr:
		return x.Sel.Name == "ErrAbortHandler"
	}
	return false
}

func (a *auditor) walkFuncBody(body *ast.BlockStmt, isTest, isHandler bool, imports map[string]string, hasMaxBytes bool) {
	// defer inside loops (stop at nested function literals, which get their own scope).
	var visit func(n ast.Node, inLoop bool)
	visit = func(n ast.Node, inLoop bool) {
		ast.Inspect(n, func(m ast.Node) bool {
			if m == n {
				return true
			}
			switch x := m.(type) {
			case *ast.FuncLit:
				visit(x.Body, false)
				return false
			case *ast.ForStmt:
				visit(x.Body, true)
				return false
			case *ast.RangeStmt:
				visit(x.Body, true)
				return false
			case *ast.DeferStmt:
				if inLoop {
					a.add("medium", "defer-in-loop", a.pos(x.Pos()), "defer inside a loop runs only when the function returns, holding every resource until then. Move the loop body into a function.")
				}
			}
			return true
		})
	}
	visit(body, false)

	if isTest || !isHandler {
		return
	}
	ast.Inspect(body, func(n ast.Node) bool {
		c, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		if isPkgCall(c, imports, "context", "Background") || isPkgCall(c, imports, "context", "TODO") {
			a.add("medium", "context-background-in-handler", a.pos(c.Pos()), "Inside a handler use r.Context(): it is cancelled when the client goes away or the server shuts down.")
		}
		if !hasMaxBytes && len(c.Args) > 0 && isRequestBody(c.Args[0]) &&
			(isPkgCall(c, imports, "io", "ReadAll") || isPkgCall(c, imports, "encoding/json", "NewDecoder") || isPkgCall(c, imports, "encoding/json/v2", "UnmarshalRead")) {
			a.add("medium", "unbounded-body", a.pos(c.Pos()), "The request body is read without a size limit. Wrap it: r.Body = http.MaxBytesReader(w, r.Body, 1<<20).")
		}
		return true
	})
}

func isRequestBody(e ast.Expr) bool {
	s, ok := e.(*ast.SelectorExpr)
	if !ok || s.Sel.Name != "Body" {
		return false
	}
	id, ok := s.X.(*ast.Ident)
	return ok && (id.Name == "r" || id.Name == "req" || id.Name == "request")
}

func (a *auditor) checkCall(c *ast.CallExpr, isTest, isMain bool, imports map[string]string) {
	// SQL built from strings (tests build fixture SQL freely, so skip them).
	if sel, ok := c.Fun.(*ast.SelectorExpr); ok && queryFuncs[sel.Sel.Name] && !isTest {
		for i, arg := range c.Args {
			if i > 1 {
				break
			}
			if isDynamicSQL(arg, imports) {
				a.add("high", "sql-string-building", a.pos(arg.Pos()), "SQL assembled with fmt.Sprintf or + is an injection risk. Use placeholders ($1, $2) and pass values as arguments (sqlc generates this for you).")
				break
			}
		}
	}
	// SQL assembled by Sprintf, even when stored in a variable before the query call.
	if isPkgCall(c, imports, "fmt", "Sprintf") && len(c.Args) > 1 && !isTest {
		if lit, ok := c.Args[0].(*ast.BasicLit); ok && lit.Kind == token.STRING {
			if s, _ := strconv.Unquote(lit.Value); sqlFormat.MatchString(s) {
				a.add("high", "sql-string-building", a.pos(c.Pos()), "SQL assembled with fmt.Sprintf is an injection risk. Pass values as $1, $2 arguments (sqlc generates this). Identifiers can't be parameters: allowlist them or quote with pgx.Identifier{...}.Sanitize().")
			}
		}
	}
	// http.Error(w, err.Error(), ...) sends internal details to the client.
	if isPkgCall(c, imports, "net/http", "Error") && len(c.Args) >= 2 && !isTest {
		if inner, ok := c.Args[1].(*ast.CallExpr); ok {
			if sel, ok := inner.Fun.(*ast.SelectorExpr); ok && sel.Sel.Name == "Error" && isErrIdent(sel.X) {
				a.add("medium", "error-leak", a.pos(c.Pos()), "http.Error(w, err.Error(), ...) leaks internal details (SQL, hosts, paths) to clients. Log err with the request context; send a generic message.")
			}
		}
	}
	// fmt.Errorf with an error formatted by %v or %s.
	if isPkgCall(c, imports, "fmt", "Errorf") && len(c.Args) >= 2 {
		if lit, ok := c.Args[0].(*ast.BasicLit); ok && lit.Kind == token.STRING {
			format, _ := strconv.Unquote(lit.Value)
			verbs := formatVerbs(format)
			for i, arg := range c.Args[1:] {
				if i < len(verbs) && (verbs[i] == 'v' || verbs[i] == 's') && isErrIdent(arg) {
					a.add("medium", "error-not-wrapped", a.pos(c.Pos()), "fmt.Errorf formats an error with %"+string(verbs[i])+", which breaks errors.Is/As. Use %w.")
					break
				}
			}
		}
	}
	if isPkgCall(c, imports, "net/http", "ListenAndServe") || isPkgCall(c, imports, "net/http", "ListenAndServeTLS") {
		a.add("high", "server-no-timeouts", a.pos(c.Pos()), "http.ListenAndServe has no timeouts (Slowloris) and no graceful shutdown. Use an http.Server with ReadHeaderTimeout and friends, and Shutdown on SIGTERM.")
		a.listenAndServe = append(a.listenAndServe, a.pos(c.Pos()))
	}
	if sel, ok := c.Fun.(*ast.SelectorExpr); ok {
		switch sel.Sel.Name {
		case "Shutdown":
			a.hasShutdown = true
		case "ListenAndServe", "ListenAndServeTLS":
			if _, pkgLevel := imports[identName(sel.X)]; !pkgLevel {
				a.listenAndServe = append(a.listenAndServe, a.pos(c.Pos()))
			}
		}
	}
	if isTest {
		if isPkgCall(c, imports, "time", "Sleep") {
			a.add("low", "sleep-in-test", a.pos(c.Pos()), "time.Sleep makes tests slow and flaky. Synchronize with channels, or use testing/synctest for time-dependent code.")
		}
		return
	}
	if !isMain {
		for _, fn := range []string{"Fatal", "Fatalf", "Fatalln"} {
			if isPkgCall(c, imports, "log", fn) {
				a.add("medium", "exit-outside-main", a.pos(c.Pos()), "log."+fn+" exits the process from a library, skipping defers and making the code untestable. Return an error.")
			}
		}
		if isPkgCall(c, imports, "os", "Exit") {
			a.add("medium", "exit-outside-main", a.pos(c.Pos()), "os.Exit outside package main skips defers and can't be tested. Return an error to main.")
		}
	}
	for _, fn := range []string{"Get", "Post", "Head", "PostForm"} {
		if isPkgCall(c, imports, "net/http", fn) {
			a.add("medium", "default-http-client", a.pos(c.Pos()), "http."+fn+" uses the default client: no timeout and no context. Build a request with http.NewRequestWithContext and use a client with Timeout set.")
		}
	}
	if isPkgCall(c, imports, "net/http", "HandleFunc") || isPkgCall(c, imports, "net/http", "Handle") {
		a.add("medium", "default-serve-mux", a.pos(c.Pos()), "Registering on http.DefaultServeMux shares a global with every imported package (pprof, expvar). Create mux := http.NewServeMux().")
	}
}

func (a *auditor) checkCompositeLit(x *ast.CompositeLit, imports map[string]string) {
	if isSelector(x.Type, imports, "net/http", "Client") {
		for _, el := range x.Elts {
			if kv, ok := el.(*ast.KeyValueExpr); ok && identName(kv.Key) == "Timeout" {
				return
			}
		}
		a.add("medium", "client-no-timeout", a.pos(x.Pos()), "http.Client without Timeout can hang forever on a slow server. Set Timeout (and use request contexts).")
		return
	}
	if !isSelector(x.Type, imports, "net/http", "Server") {
		return
	}
	for _, el := range x.Elts {
		if kv, ok := el.(*ast.KeyValueExpr); ok {
			if k := identName(kv.Key); k == "ReadHeaderTimeout" || k == "ReadTimeout" {
				return
			}
		}
	}
	a.add("high", "server-no-timeouts", a.pos(x.Pos()), "http.Server without ReadHeaderTimeout/ReadTimeout is open to Slowloris. Set ReadHeaderTimeout, ReadTimeout, WriteTimeout, and IdleTimeout.")
}

func (a *auditor) checkErrCompare(x *ast.BinaryExpr) {
	l, r := identName(x.X), identName(x.Y)
	if l != "err" && r != "err" {
		return
	}
	other := x.Y
	if r == "err" {
		other = x.X
	}
	name := identName(other)
	if sel, ok := other.(*ast.SelectorExpr); ok {
		name = sel.Sel.Name
	}
	if name != "nil" && sentinelErr.MatchString(name) {
		a.add("medium", "error-equality", a.pos(x.Pos()), fmt.Sprintf("Comparing err with %s misses wrapped errors. Use errors.Is(err, %s).", x.Op, name))
	}
}

// ---------- non-Go files ----------

var (
	goDirective = regexp.MustCompile(`(?m)^go\s+1\.(\d+)`)
	replaceLine = regexp.MustCompile(`(?m)^\s*(?:replace\s+)?[^\s]+(?:\s+v[^\s]+)?\s+=>\s+(\.{1,2}/[^\s]*)`)
	fromLine    = regexp.MustCompile(`(?im)^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)`)
)

var discouragedModules = map[string][2]string{
	"github.com/sirupsen/logrus":  {"low", "logrus is in maintenance mode. Use log/slog from the standard library."},
	"github.com/lib/pq":           {"low", "lib/pq is in maintenance mode. Use github.com/jackc/pgx/v5 (pgxpool)."},
	"github.com/pkg/errors":       {"low", "github.com/pkg/errors is archived. Use fmt.Errorf with %w."},
	"github.com/gorilla/mux":      {"low", "Go 1.22+ http.ServeMux does methods and {wildcards}. Drop the router dependency."},
	"github.com/go-chi/chi/v5":    {"low", "Go 1.22+ http.ServeMux does methods and {wildcards}. Keep chi only if you need its middleware ecosystem."},
	"github.com/gin-gonic/gin":    {"low", "Gin replaces net/http idioms with its own context. Prefer net/http + ServeMux."},
	"github.com/labstack/echo/v4": {"low", "Echo replaces net/http idioms with its own context. Prefer net/http + ServeMux."},
	"github.com/gofiber/fiber/v2": {"low", "Fiber is built on fasthttp, not net/http; most of the ecosystem won't fit. Prefer net/http."},
	"github.com/golang/protobuf":  {"low", "Deprecated. Use google.golang.org/protobuf."},
}

func (a *auditor) checkOtherFile(path string) {
	data, err := os.ReadFile(path)
	if err != nil {
		return
	}
	text := string(data)
	name := filepath.Base(path)
	switch {
	case name == "go.mod":
		a.checkGoMod(path, text)
	case strings.Contains(filepath.ToSlash(path), ".github/workflows/"):
		for i, line := range strings.Split(text, "\n") {
			if strings.Contains(line, "go test") && !strings.Contains(line, "-race") && !strings.Contains(line, "-run") && !strings.HasPrefix(strings.TrimSpace(line), "#") {
				a.add("low", "ci-no-race", fmt.Sprintf("%s:%d", a.rel(path), i+1), "CI runs go test without -race. Data races are silent until production; add -race.")
			}
		}
	default:
		a.checkDockerfile(path, text)
	}
}

func (a *auditor) checkGoMod(path, text string) {
	loc := a.rel(path)
	if m := goDirective.FindStringSubmatch(text); m != nil {
		if minor, _ := strconv.Atoi(m[1]); minor < 25 {
			a.add("low", "old-go-directive", loc, fmt.Sprintf("go 1.%d is out of support (only the two newest releases get security fixes). Move to go 1.26+ and run go fix ./... .", minor))
		}
	}
	for _, m := range replaceLine.FindAllStringSubmatch(text, -1) {
		a.add("medium", "local-replace", loc, fmt.Sprintf("replace => %s only works on this machine and breaks go install for consumers. Use go.work for local multi-module development.", m[1]))
	}
	requires := strings.Contains(text, "require")
	dir := filepath.Dir(path)
	if requires {
		if _, err := os.Stat(filepath.Join(dir, "go.sum")); errors.Is(err, fs.ErrNotExist) {
			a.add("medium", "missing-go-sum", loc, "go.mod has requirements but no go.sum is committed. Run go mod tidy and commit go.sum for reproducible, verified builds.")
		}
	}
	sc := bufio.NewScanner(strings.NewReader(text))
	for sc.Scan() {
		fields := strings.Fields(strings.TrimPrefix(strings.TrimSpace(sc.Text()), "require "))
		if len(fields) == 0 {
			continue
		}
		if d, ok := discouragedModules[fields[0]]; ok {
			a.add(d[0], "discouraged-module", loc, fields[0]+": "+d[1])
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "tools.go")); err == nil {
		a.add("low", "tools-go", a.rel(filepath.Join(dir, "tools.go")), "tools.go with blank imports is superseded by the go.mod tool directive (Go 1.24+): go get -tool <pkg>@<version>, then go tool <name>.")
	}
}

func (a *auditor) checkDockerfile(path, text string) {
	loc := a.rel(path)
	froms := fromLine.FindAllStringSubmatch(text, -1)
	if len(froms) == 0 {
		return
	}
	final := strings.ToLower(froms[len(froms)-1][1])
	if strings.HasPrefix(final, "golang:") {
		a.add("medium", "toolchain-runtime-image", loc, "The final stage is the golang image (~800 MB, compiler and shell included). Copy the binary into gcr.io/distroless/static-debian13:nonroot.")
	}
	hasBuild := strings.Contains(text, "go build")
	if !hasBuild {
		return
	}
	static := final == "scratch" || strings.Contains(final, "distroless/static")
	if static && !strings.Contains(text, "CGO_ENABLED=0") {
		a.add("high", "cgo-static-image", loc, "go build without CGO_ENABLED=0 can produce a dynamically linked binary that fails to start on scratch/distroless-static (\"no such file or directory\"). Set CGO_ENABLED=0.")
	}
	if !strings.Contains(text, "-trimpath") {
		a.add("low", "no-trimpath", loc, "Add -trimpath (and -ldflags=\"-s -w\") so release binaries are reproducible and don't embed build paths.")
	}
}

// ---------- layout ----------

func (a *auditor) checkLayout() {
	if st, err := os.Stat(filepath.Join(a.root, "pkg")); err == nil && st.IsDir() {
		a.add("low", "pkg-dir", "pkg/", "A top-level pkg/ adds a path segment and signals nothing. Put private code in internal/ and public packages at the module root.")
	}
}

// ---------- AST helpers ----------

func identName(e ast.Expr) string {
	if id, ok := e.(*ast.Ident); ok {
		return id.Name
	}
	return ""
}

func isErrIdent(e ast.Expr) bool {
	n := identName(e)
	return n == "err" || strings.HasSuffix(n, "Err") || strings.HasPrefix(n, "err") && len(n) > 3 && n[3] >= 'A' && n[3] <= 'Z'
}

// isSelector reports whether e is pkg.Name where pkg is imported from importPath.
func isSelector(e ast.Expr, imports map[string]string, importPath, name string) bool {
	if st, ok := e.(*ast.StarExpr); ok {
		e = st.X
	}
	sel, ok := e.(*ast.SelectorExpr)
	if !ok || sel.Sel.Name != name {
		return false
	}
	return imports[identName(sel.X)] == importPath
}

func isPkgCall(c *ast.CallExpr, imports map[string]string, importPath, name string) bool {
	return isSelector(c.Fun, imports, importPath, name)
}

func hasParamType(ft *ast.FuncType, imports map[string]string, importPath, name string) bool {
	if ft.Params == nil {
		return false
	}
	for _, p := range ft.Params.List {
		if isSelector(p.Type, imports, importPath, name) {
			return true
		}
	}
	return false
}

func isDynamicSQL(e ast.Expr, imports map[string]string) bool {
	switch x := e.(type) {
	case *ast.CallExpr:
		if isPkgCall(x, imports, "fmt", "Sprintf") && len(x.Args) > 1 {
			if lit, ok := x.Args[0].(*ast.BasicLit); ok && lit.Kind == token.STRING {
				s, _ := strconv.Unquote(lit.Value)
				return sqlVerb.MatchString(s) && !sqlFormat.MatchString(s) // the latter is reported at the Sprintf
			}
		}
	case *ast.BinaryExpr:
		if x.Op != token.ADD {
			return false
		}
		lit := leftmostString(x)
		return lit != "" && sqlVerb.MatchString(lit) && !allLiterals(x)
	}
	return false
}

func leftmostString(e ast.Expr) string {
	for {
		switch x := e.(type) {
		case *ast.BinaryExpr:
			e = x.X
		case *ast.BasicLit:
			if x.Kind == token.STRING {
				s, _ := strconv.Unquote(x.Value)
				return s
			}
			return ""
		default:
			return ""
		}
	}
}

func allLiterals(e ast.Expr) bool {
	switch x := e.(type) {
	case *ast.BinaryExpr:
		return allLiterals(x.X) && allLiterals(x.Y)
	case *ast.BasicLit:
		return true
	}
	return false
}

// formatVerbs returns the verb letters of a printf format, in argument order.
func formatVerbs(format string) []rune {
	var verbs []rune
	rs := []rune(format)
	for i := 0; i < len(rs); i++ {
		if rs[i] != '%' {
			continue
		}
		i++
		for i < len(rs) && strings.ContainsRune("+-# 0123456789.*[]", rs[i]) {
			i++
		}
		if i < len(rs) && rs[i] != '%' {
			verbs = append(verbs, rs[i])
		}
	}
	return verbs
}

func firstLine(s string) string {
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		return s[:i]
	}
	return s
}
