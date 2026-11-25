package controller_test

import (
	"net/http"

	"aisol-env-booking-api/internal/controller"
	"code.iflytek.com/TJ_Base/aisol-framework-golang/server"
)

// Guards use the same SDK binding, access middleware and controllers as main.
// The requests under test must be rejected before any repository call.
func guardRouter() http.Handler {
	server.InitServer(server.ServerConfig{SvcName: "aisol-env-booking-api", ContextPath: "/api"})
	controller.InitBusinessHTTP()
	user := controller.PrepareRequest(controller.UserAccess)
	admin := controller.PrepareRequest(controller.AdminAccess)
	server.GET("/bookings", controller.ListBookingsController, user)
	server.POST("/bookings", controller.CreateBookingController, user)
	server.DELETE("/bookings/:id", controller.CancelLegacyBookingController, user)
	server.GET("/maintenance", controller.ListMaintenanceController, user)
	server.POST("/maintenance", controller.CreateMaintenanceController, admin)
	server.DELETE("/maintenance/:id", controller.CancelLegacyMaintenanceController, admin)
	server.GET("/waitlist", controller.ListWaitlistController, user)
	server.POST("/waitlist", controller.CreateWaitlistController, user)
	return server.Svr.Engine
}
