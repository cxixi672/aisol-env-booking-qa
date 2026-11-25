package controller_test

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDIWU70Guards(t *testing.T) {
	router := guardRouter()
	const path = "/api/bookings"
	const body = `{"env":"env-a","start":"2030-01-02T10:00:00Z","end":"2030-01-02T11:00:00Z"}`
	for _, tc := range []struct {
		name, method, path, user, key, input string
		code                                 string
	}{
		{"missing-user", "GET", path, "", "", "", "FORBIDDEN"},
		{"unknown-user", "POST", path, "guest", "k", body, "FORBIDDEN"},
		{"no-key", "POST", path, "alice", "", body, "INVALID_INPUT"},
		{"extra-identity-field", "POST", path, "alice", "k", strings.Replace(body, "{", `{"user":"bob",`, 1), "INVALID_INPUT"},
		{"empty-slot", "POST", path, "alice", "k", strings.Replace(body, "11:00", "10:00", 1), "INVALID_INPUT"},
		{"unknown-env", "POST", path, "alice", "k", strings.Replace(body, "env-a", "env-c", 1), "INVALID_INPUT"},
		{"missing-range", "GET", path + "?env=env-a", "alice", "", "", "INVALID_INPUT"},
		{"invalid-id", "DELETE", path + "/0", "alice", "", "", "INVALID_INPUT"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(tc.method, tc.path, strings.NewReader(tc.input))
			if tc.user != "" {
				req.Header.Set("X-User", tc.user)
			}
			if tc.key != "" {
				req.Header.Set("Idempotency-Key", tc.key)
			}
			if tc.input != "" {
				req.Header.Set("Content-Type", "application/json")
			}
			w := httptest.NewRecorder()
			router.ServeHTTP(w, req)
			t.Logf("%s %s user=%q key=%q body=%s -> %d %s", tc.method, tc.path, tc.user, tc.key, tc.input, w.Code, w.Body.String())
			var env struct {
				Code, Desc string
				Data       json.RawMessage
			}
			if json.Unmarshal(w.Body.Bytes(), &env) != nil || w.Code != 200 || env.Code != tc.code || env.Desc == "" || (len(env.Data) != 0 && string(env.Data) != "null") {
				t.Fatal("unexpected rejection envelope")
			}
		})
	}
}
