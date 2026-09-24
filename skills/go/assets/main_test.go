package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestRun(t *testing.T) {
	t.Parallel()
	env := func(m map[string]string) func(string) string { return func(k string) string { return m[k] } }
	tests := []struct {
		name    string
		args    []string
		env     map[string]string
		wantOut string
		wantErr string
	}{
		{name: "version", args: []string{"version"}, wantOut: "dev"},
		{name: "unknown command", args: []string{"frobnicate"}, wantErr: "unknown command"},
		{name: "missing DATABASE_URL", args: []string{"serve"}, wantErr: "DATABASE_URL is required"},
		{name: "bad LOG_LEVEL", args: []string{"migrate"}, env: map[string]string{"DATABASE_URL": "postgres://x", "LOG_LEVEL": "loud"}, wantErr: "LOG_LEVEL"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			var out bytes.Buffer
			err := run(t.Context(), tt.args, env(tt.env), &out)
			if tt.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), tt.wantErr) {
					t.Fatalf("run(%v) err = %v, want %q", tt.args, err, tt.wantErr)
				}
				return
			}
			if err != nil || !strings.Contains(out.String(), tt.wantOut) {
				t.Fatalf("run(%v) = %q, %v", tt.args, out.String(), err)
			}
		})
	}
}
