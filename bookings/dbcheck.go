// Run with the candidate API module's pinned MySQL driver and sqrl version.
package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/elgris/sqrl"
	_ "github.com/go-sql-driver/mysql"
)

type record struct {
	ID, User, Env, Start, End, Status string
}

type identity struct {
	user, key string
}

func readRun(path string) (map[identity]*record, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	if !scanner.Scan() || !strings.HasPrefix(scanner.Text(), "TARGET external ") {
		return nil, errors.New("expected external candidate run")
	}
	keys := make(map[identity]*record)
	var passed bool
	for scanner.Scan() {
		if scanner.Text() == "PASS" {
			passed = true
			continue
		}
		var exchange struct {
			Method, Response string
			Status           int
			Headers          map[string]string
		}
		if err := json.Unmarshal(scanner.Bytes(), &exchange); err != nil {
			return nil, err
		}
		k := identity{exchange.Headers["X-User"], exchange.Headers["Idempotency-Key"]}
		if exchange.Method != "POST" || k.key == "" {
			continue
		}
		if _, exists := keys[k]; !exists {
			keys[k] = nil
		}
		if exchange.Status == 201 {
			var response struct{ Data record }
			if err := json.Unmarshal([]byte(exchange.Response), &response); err != nil {
				return nil, err
			}
			keys[k] = &response.Data
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if !passed || len(keys) == 0 {
		return nil, errors.New("incomplete HTTP acceptance run")
	}
	return keys, nil
}

func verify(ctx context.Context, db *sql.DB, k identity, want *record) error {
	digest := sha256.Sum256([]byte(k.key))
	q := sqrl.Select("response").From("idempotency_keys").Where(sqrl.Eq{
		"user_id": k.user, "resource": "bookings", "request_key": digest[:],
	})
	query, args, err := q.ToSql()
	if err != nil {
		return err
	}
	var raw []byte
	err = db.QueryRowContext(ctx, query, args...).Scan(&raw)
	if want == nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil
		}
		if err != nil {
			return err
		}
		return errors.New("rejected request retained idempotency row")
	}
	if err != nil {
		return err
	}
	var cached record
	if err := json.Unmarshal(raw, &cached); err != nil {
		return err
	}
	if cached != *want {
		return errors.New("cached success differs from original HTTP response")
	}

	query, args, err = sqrl.Select("env", "start_at", "end_at", "user_id", "status").From("bookings").
		Where(sqrl.Eq{"id": want.ID}).ToSql()
	if err != nil {
		return err
	}
	var env, user, status string
	var start, end int64
	if err := db.QueryRowContext(ctx, query, args...).Scan(&env, &start, &end, &user, &status); err != nil {
		return err
	}
	if env != want.Env || user != want.User || status != "cancelled" ||
		time.Unix(start, 0).UTC().Format(time.RFC3339) != want.Start ||
		time.Unix(end, 0).UTC().Format(time.RFC3339) != want.End {
		return fmt.Errorf("unexpected final state of booking %s", want.ID)
	}
	return nil
}

func run() error {
	if len(os.Args) != 2 {
		return errors.New("expected HTTP run log path")
	}
	keys, err := readRun(os.Args[1])
	if err != nil {
		return err
	}
	dsn := os.Getenv("BOOKING_QA_MYSQL_DSN")
	if dsn == "" {
		return errors.New("BOOKING_QA_MYSQL_DSN is required")
	}
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		return errors.New("invalid MySQL configuration")
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	for k, want := range keys {
		if err := verify(ctx, db, k, want); err != nil {
			return fmt.Errorf("verify user=%q key=%q: %w", k.user, k.key, err)
		}
	}
	fmt.Printf("PASS MySQL terminal state for %d request identities\n", len(keys))
	return nil
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
