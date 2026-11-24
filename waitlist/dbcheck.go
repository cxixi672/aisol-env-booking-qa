// Run from the tested API module to reuse its pinned MySQL and sqrl dependencies.
package main

import (
	"context"
	"database/sql"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/elgris/sqrl"
	_ "github.com/go-sql-driver/mysql"
)

type row struct {
	id, start, end int64
	user, status   string
	link           sql.NullInt64
}

func read(ctx context.Context, db *sql.DB, table string, day time.Time, link string) ([]row, error) {
	columns := []string{"id", "start_at", "end_at", "user_id", "status"}
	if link != "" {
		columns = append(columns, link)
	}
	start := day.Add(10 * time.Hour).Unix()
	query, args, err := sqrl.Select(columns...).From(table).Where(sqrl.And{
		sqrl.Eq{"env": "env-a"}, sqrl.Lt{"start_at": start + 3600}, sqrl.Gt{"end_at": start},
	}).OrderBy("id").ToSql()
	if err != nil {
		return nil, err
	}
	result, err := db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer result.Close()
	var records []row
	for result.Next() {
		var r row
		dest := []any{&r.id, &r.start, &r.end, &r.user, &r.status}
		if link != "" {
			dest = append(dest, &r.link)
		}
		if err := result.Scan(dest...); err != nil {
			return nil, err
		}
		records = append(records, r)
	}
	return records, result.Err()
}

func check(ctx context.Context, db *sql.DB, day time.Time, skip bool) error {
	bookings, err := read(ctx, db, "bookings", day, "waitlist_id")
	if err != nil {
		return err
	}
	queue, err := read(ctx, db, "waitlist", day, "booking_id")
	if err != nil {
		return err
	}
	maintenance, err := read(ctx, db, "maintenance", day, "")
	if err != nil {
		return err
	}
	if len(bookings) != 3 || len(queue) != 2 || len(maintenance) != 1 {
		return fmt.Errorf("unexpected row counts bookings=%d waitlist=%d maintenance=%d", len(bookings), len(queue), len(maintenance))
	}
	start := day.Add(10 * time.Hour).Unix()
	original, m := bookings[0], maintenance[0]
	if original.status != "cancelled" || original.user != "alice" || original.start != start || original.end != start+1800 || original.link.Valid ||
		m.status != "cancelled" || m.user != "admin" || m.start != start+1800 || m.end != start+3600 {
		return fmt.Errorf("unexpected original booking or maintenance state")
	}
	for i, q := range queue {
		b := bookings[i+1]
		end, user := start+3600, "bob"
		if skip {
			b = bookings[2-i]
			if i == 1 {
				end = start + 1800
			}
		} else if i == 1 {
			user = "carol"
		}
		if q.start != start || q.end != end || q.user != user || q.status != "promoted" ||
			b.status != "cancelled" || b.start != q.start || b.end != q.end || b.user != q.user ||
			!q.link.Valid || !b.link.Valid || q.link.Int64 != b.id || b.link.Int64 != q.id {
			return fmt.Errorf("unexpected booking link or state for queue ID %d", q.id)
		}
	}
	return nil
}

func main() {
	date := flag.String("day", "2030-01-02", "first UTC test date")
	flag.Parse()
	day, err := time.Parse("2006-01-02", *date)
	if err != nil {
		panic(err)
	}
	dsn := os.Getenv("MYSQL_DSN")
	if dsn == "" {
		fmt.Fprintln(os.Stderr, "SKIP: authorized MYSQL_DSN required")
		os.Exit(2)
	}
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		fmt.Fprintln(os.Stderr, "invalid MYSQL_DSN")
		os.Exit(1)
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	for i := 0; i < 2; i++ {
		d := day.AddDate(0, 0, i)
		if err := check(ctx, db, d, i == 1); err != nil {
			fmt.Fprintf(os.Stderr, "FAIL %s: %v\n", d.Format("2006-01-02"), err)
			os.Exit(1)
		}
		fmt.Println("PASS database final state", d.Format("2006-01-02"))
	}
}
