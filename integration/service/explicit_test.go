package service_test

import (
	"context"
	"errors"
	"os"
	"strconv"
	"testing"
	"time"

	"aisol-env-booking-api/internal/common"
	"aisol-env-booking-api/internal/dto"
	"aisol-env-booking-api/internal/repository"
	"aisol-env-booking-api/internal/service"
	"code.iflytek.com/TJ_Base/aisol-framework-golang/sqla"
)

// Run only against a fresh migrated QA database.
func TestExplicitOperator(t *testing.T) {
	dsn := os.Getenv("BOOKING_TEST_MYSQL_DSN")
	if dsn == "" {
		t.Fatal("isolated BOOKING_TEST_MYSQL_DSN required")
	}
	store := repository.DataSourceInit(sqla.DatabaseConfig{Type: "mysql", Dsn: dsn, MaxOpenConns: 2, MaxIdleConns: 2})
	t.Cleanup(func() { _ = store.Close() })
	queue := service.NewWaitlist(store)
	deps := service.SlotDependencies{Store: store, Release: queue.Promote}
	bookings := service.NewBookings(deps)
	maintenance := service.NewMaintenance(deps)
	ctx := context.Background()
	start := time.Date(2032, 1, 2, 10, 0, 0, 0, time.UTC).Unix()
	slot := dto.Slot{Env: "env-b", Start: start, End: start + 3600}
	alice := common.Operator{UserID: "alice"}
	bob := common.Operator{UserID: "bob"}
	cmd := service.CreateSlotCommand{Operator: alice, Slot: slot, IdempotencyKey: "qa-explicit-book"}
	if _, err := maintenance.CreateIdempotent(ctx, cmd); !errors.Is(err, common.ErrForbidden) {
		t.Fatalf("maintenance permission: %v", err)
	}
	first, err := bookings.CreateIdempotent(ctx, cmd)
	if err != nil || first.User != "alice" || first.Status != "active" {
		t.Fatalf("create: %+v %v", first, err)
	}
	replay, err := bookings.CreateIdempotent(ctx, cmd)
	if err != nil || replay != first {
		t.Fatalf("replay: %+v %v", replay, err)
	}
	queued, err := queue.CreateIdempotent(ctx, service.CreateSlotCommand{Operator: bob, Slot: slot, IdempotencyKey: "qa-explicit-queue"})
	if err != nil || queued.User != "bob" || queued.Status != "waiting" {
		t.Fatalf("enqueue: %+v %v", queued, err)
	}
	aliceRows, err := queue.List(ctx, service.ListSlotsQuery{Operator: alice, Slot: slot})
	if err != nil || len(aliceRows) != 0 {
		t.Fatalf("alice queue: %+v %v", aliceRows, err)
	}
	id, err := strconv.ParseInt(first.ID, 10, 64)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := bookings.Cancel(ctx, service.CancelSlotCommand{Operator: bob, ID: id}); !errors.Is(err, common.ErrForbidden) {
		t.Fatalf("booking owner check: %v", err)
	}
	cancelled, err := bookings.Cancel(ctx, service.CancelSlotCommand{Operator: alice, ID: id})
	if err != nil || cancelled.Status != "cancelled" {
		t.Fatalf("cancel: %+v %v", cancelled, err)
	}
	rows, err := queue.List(ctx, service.ListSlotsQuery{Operator: bob, Slot: slot})
	if err != nil || len(rows) != 1 || rows[0].ID != queued.ID || rows[0].Status != "promoted" || rows[0].BookingID == "" {
		t.Fatalf("promotion: %+v %v", rows, err)
	}
}
