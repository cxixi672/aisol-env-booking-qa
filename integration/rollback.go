// Run from the candidate API module with MYSQL_DSN for its isolated test database.
// The API must use the same database. Example: go run ../qa-integration/integration/rollback.go -port 18062
package main

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/elgris/sqrl"
	_ "github.com/go-sql-driver/mysql"
)

type record struct{ ID, Status, BookingID string }
type envelope struct {
	Code string
	Data json.RawMessage
}
type fixture struct {
	base, key string
	db        *sql.DB
	ctx       context.Context
	slot      map[string]string
}

func (f fixture) request(method, path, user string, expected string) (record, error) {
	var payload []byte
	if method == "POST" {
		var err error
		payload, err = json.Marshal(f.slot)
		if err != nil {
			return record{}, err
		}
	}
	req, err := http.NewRequestWithContext(f.ctx, method, f.base+path, bytes.NewReader(payload))
	if err != nil {
		return record{}, err
	}
	req.Header.Set("X-User", user)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", f.key)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return record{}, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 16384))
	if err != nil {
		return record{}, err
	}
	var result envelope
	if err = json.Unmarshal(body, &result); err != nil {
		return record{}, err
	}
	if resp.StatusCode != http.StatusOK || result.Code != expected {
		return record{}, fmt.Errorf("%s %s: HTTP %d code %q, expected 200 %q", method, path, resp.StatusCode, result.Code, expected)
	}
	if expected != "000000" {
		if len(result.Data) != 0 && string(result.Data) != "null" {
			return record{}, errors.New("unexpected error payload")
		}
		return record{}, nil
	}
	var r record
	if err = json.Unmarshal(result.Data, &r); err != nil {
		return r, err
	}
	if r.ID == "" {
		return r, errors.New("missing record id")
	}
	return r, nil
}

func (f fixture) exec(b sqrl.Sqlizer) (sql.Result, error) {
	query, args, err := b.ToSql()
	if err != nil {
		return nil, err
	}
	return f.db.ExecContext(f.ctx, query, args...)
}
func (f fixture) state(table, id string) (string, error) {
	query, args, err := sqrl.Select("status").From(table).Where(sqrl.Eq{"id": id}).ToSql()
	if err != nil {
		return "", err
	}
	var status string
	err = f.db.QueryRowContext(f.ctx, query, args...).Scan(&status)
	return status, err
}

type releaseCase struct{ resource, operator string }

func (f fixture) check(c releaseCase) (err error) {
	// Use a fresh, migrated isolated test database with no active bookings or queue for this slot.
	release, err := f.request("POST", "/"+c.resource, c.operator, "000000")
	if err != nil {
		return err
	}
	q, err := f.request("POST", "/waitlist", "bob", "000000")
	if err != nil {
		return err
	}
	start, _ := time.Parse(time.RFC3339, f.slot["start"])
	end, _ := time.Parse(time.RFC3339, f.slot["end"])
	// Occupy the unique promotion link on a cancelled fixture row. Promotion must fail
	// after the release changed the original booking, forcing the whole release to roll back.
	res, err := f.exec(sqrl.Insert("bookings").Columns("env", "start_at", "end_at", "user_id", "status", "waitlist_id").Values("env-a", start.Unix(), end.Unix(), "bob", "cancelled", q.ID))
	if err != nil {
		return err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return err
	}
	cleanup := func() error {
		_, e := f.exec(sqrl.Delete("bookings").Where(sqrl.Eq{"id": id, "waitlist_id": q.ID, "status": "cancelled"}))
		return e
	}
	defer func() { err = errors.Join(err, cleanup()) }()
	path := "/" + c.resource + "/" + release.ID
	if _, err = f.request("DELETE", path, c.operator, "INTERNAL_ERROR"); err != nil {
		return err
	}
	for _, check := range []struct{ table, id, want string }{{c.resource, release.ID, "active"}, {"waitlist", q.ID, "waiting"}} {
		got, e := f.state(check.table, check.id)
		if e != nil {
			return e
		}
		if got != check.want {
			return fmt.Errorf("%s %s: got %s, want %s", check.table, check.id, got, check.want)
		}
	}
	if err = cleanup(); err != nil {
		return err
	}
	if _, err = f.request("DELETE", path, c.operator, "000000"); err != nil {
		return err
	}
	query, args, err := sqrl.Select("booking_id").From("waitlist").Where(sqrl.Eq{"id": q.ID, "status": "promoted"}).ToSql()
	if err != nil {
		return err
	}
	var promoted string
	if err = f.db.QueryRowContext(f.ctx, query, args...).Scan(&promoted); err != nil {
		return err
	}
	_, err = f.request("DELETE", "/bookings/"+promoted, "bob", "000000")
	return err
}
func main() {
	port := flag.Int("port", 18062, "candidate loopback API port")
	flag.Parse()
	dsn := os.Getenv("MYSQL_DSN")
	if dsn == "" {
		fmt.Fprintln(os.Stderr, "SKIP: isolated MYSQL_DSN required")
		os.Exit(2)
	}
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		fmt.Fprintln(os.Stderr, "invalid database configuration")
		os.Exit(1)
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	f := fixture{fmt.Sprintf("http://127.0.0.1:%d/api", *port), fmt.Sprintf("rollback-%d", time.Now().UnixNano()), db, ctx, map[string]string{"env": "env-a", "start": "2030-01-04T10:00:00Z", "end": "2030-01-04T11:00:00Z"}}
	for _, c := range []releaseCase{{resource: "bookings", operator: "alice"}, {resource: "maintenance", operator: "admin"}} {
		f.key = fmt.Sprintf("rollback-%s-%d", c.resource, time.Now().UnixNano())
		if err = f.check(c); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		fmt.Println("PASS", c.resource, "release rollback, retry and promotion")
	}
}
