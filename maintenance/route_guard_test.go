package controller_test

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

// These requests must return before opening a transaction or accessing the store.
func TestMaintenanceGuardsDIWU68(t *testing.T) {
	router := guardRouter()
	for _, c := range []struct {
		method, path, user, key, body string
		code                          string
	}{
		{"POST", "/api/maintenance", "admin", "qa", `{"env":"env-a","start":"2030-01-02T10:00:00Z","end":"2030-01-02T11:00:00Z","user":"alice"}`, "INVALID_INPUT"},
		{"GET", "/api/maintenance", "", "", "", "FORBIDDEN"},
		{"GET", "/api/maintenance", "unknown", "", "", "FORBIDDEN"},
		{"GET", "/api/maintenance?env=env-a", "alice", "", "", "INVALID_INPUT"},
		{"DELETE", "/api/maintenance/1", "bob", "", "", "FORBIDDEN"},
		{"DELETE", "/api/maintenance/0", "admin", "", "", "INVALID_INPUT"},
		{"POST", "/api/maintenance", "alice", "qa", "{}", "FORBIDDEN"},
		{"POST", "/api/maintenance", "admin", "", `{"env":"env-a","start":"2030-01-02T10:00:00Z","end":"2030-01-02T11:00:00Z"}`, "INVALID_INPUT"},
		{"POST", "/api/maintenance", "admin", "qa", `{"env":"env-a","start":"2030-01-02T10:00:00Z","end":"2030-01-02T10:00:00Z"}`, "INVALID_INPUT"},
	} {
		req := httptest.NewRequest(c.method, c.path, strings.NewReader(c.body))
		req.Header.Set("X-User", c.user)
		req.Header.Set("Idempotency-Key", c.key)
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		router.ServeHTTP(w, req)
		var body struct {
			Code string
			Desc string
			Data json.RawMessage
		}
		t.Logf("%s %s user=%q key=%q input=%s -> %d %s", c.method, c.path, c.user, c.key, c.body, w.Code, w.Body)
		if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil || w.Code != 200 ||
			body.Code != c.code || body.Desc == "" || (len(body.Data) != 0 && string(body.Data) != "null") {
			t.Fatalf("expected HTTP 200, code %s and absent or null data", c.code)
		}
	}
}
