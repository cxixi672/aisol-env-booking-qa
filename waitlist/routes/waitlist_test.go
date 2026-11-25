package controller_test

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

// These rejections must complete before any repository operation.
func TestDIWU63WaitlistBoundary(t *testing.T) {
	engine := guardRouter()
	const path = "/api/waitlist"
	const valid = `{"env":"env-a","start":"2030-01-02T10:00:00Z","end":"2030-01-02T11:00:00Z"}`
	for _, c := range []struct {
		name, method, query, body, user, key string
		code                                 string
	}{
		{"anonymous", "GET", "", "", "", "", "FORBIDDEN"},
		{"unknown", "POST", "", valid, "someone", "test", "FORBIDDEN"},
		{"extra identity field", "POST", "", strings.Replace(valid, "{", `{"user":"alice",`, 1), "bob", "test", "INVALID_INPUT"},
		{"missing key", "POST", "", valid, "bob", "", "INVALID_INPUT"},
		{"missing query fields", "GET", "?env=env-a", "", "bob", "", "INVALID_INPUT"},
		{"empty interval", "POST", "", strings.Replace(valid, "11:00", "10:00", 1), "bob", "test", "INVALID_INPUT"},
		{"unknown environment", "POST", "", strings.Replace(valid, "env-a", "env-z", 1), "bob", "test", "INVALID_INPUT"},
	} {
		t.Run(c.name, func(t *testing.T) {
			req := httptest.NewRequest(c.method, path+c.query, strings.NewReader(c.body))
			req.Header.Set("Content-Type", "application/json")
			if c.user != "" {
				req.Header.Set("X-User", c.user)
			}
			if c.key != "" {
				req.Header.Set("Idempotency-Key", c.key)
			}
			w := httptest.NewRecorder()
			engine.ServeHTTP(w, req)
			t.Logf("%s %s user=%q key=%q body=%s => %d %s", req.Method, req.URL, c.user, c.key, c.body, w.Code, w.Body)
			var got struct {
				Code, Desc string
				Data       json.RawMessage
			}
			if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
				t.Fatal(err)
			}
			if w.Code != 200 || got.Code != c.code || got.Desc == "" || (len(got.Data) != 0 && string(got.Data) != "null") {
				t.Fail()
			}
		})
	}
}
