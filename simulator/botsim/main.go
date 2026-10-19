// Command botsim simulates robots on a site network. Rovo robots push telemetry
// to the site MQTT broker. A Cleanix robot serves its own REST API, one per
// process. The fleet is fixed at startup from env.
package main

import (
	"context"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"robofleet/simulator/botsim/robot"
	"robofleet/simulator/botsim/runner"
	"robofleet/simulator/botsim/vendors/cleanix"
	"robofleet/simulator/botsim/vendors/rovo"
)

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stdout, nil)))

	rovoCount := env("ROVO_COUNT", 0, strconv.Atoi)
	cleanixCount := env("CLEANIX_COUNT", 0, strconv.Atoi)
	if cleanixCount > 1 {
		fatal("CLEANIX_COUNT must be 0 or 1. Each Cleanix robot needs its own process, so scale out with more containers.")
	}
	area := robot.Map{
		Width:  env("MAP_WIDTH_M", 40.0, parseFloat),
		Height: env("MAP_HEIGHT_M", 25.0, parseFloat),
	}
	chaos := robot.Chaos{
		ErrorRate: env("CHAOS_ERROR_RATE", 0.002, parseFloat),
		StuckRate: env("CHAOS_STUCK_RATE", 0.001, parseFloat),
	}
	link := runner.Link{
		DropoutRate: env("CHAOS_DROPOUT_RATE", 0.0005, parseFloat),
		DelayRate:   env("CHAOS_DELAY_RATE", 0.03, parseFloat),
	}
	tick := env("TICK", time.Second, time.ParseDuration)
	if tick <= 0 {
		fatal("TICK must be positive")
	}
	seed := env("SEED", time.Now().UnixNano(), func(s string) (int64, error) { return strconv.ParseInt(s, 10, 64) })
	simID := serialNamespace()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	sim := runner.New(simID, area, tick, seed, chaos, link)
	if _, err := sim.Start(rovo.New(env("MQTT_URL", "tcp://localhost:1883", str)), rovoCount); err != nil {
		fatal(err.Error())
	}
	if _, err := sim.Start(cleanix.New(env("CLEANIX_ADDR", ":8080", str)), cleanixCount); err != nil {
		fatal(err.Error())
	}
	slog.Info("botsim running", "sim", simID, "seed", seed, "rovo", rovoCount, "cleanix", cleanixCount, "chaos", chaos, "link", link)

	<-ctx.Done()

	slog.Info("shutting down")
	sim.Stop()
}

// serialNamespace keeps serials unique across simulator containers and stable
// across restarts. SIM_ID wins if set. Otherwise it is the container's compose
// name, like robofleet-site1-bot-cleanix-3, found by a reverse DNS lookup of its own IP. The
// Dockerfile ships nsswitch.conf so Docker DNS answers before /etc/hosts. The
// hostname is the fallback outside Docker.
func serialNamespace() string {
	if id := os.Getenv("SIM_ID"); id != "" {
		return id
	}
	host, _ := os.Hostname()
	ip := ownIP()
	if ip == "" {
		return host
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	names, err := net.DefaultResolver.LookupAddr(ctx, ip)
	if err != nil || len(names) == 0 {
		return host
	}
	return strings.SplitN(names[0], ".", 2)[0]
}

// ownIP returns the first non-loopback IPv4 address, or "".
func ownIP() string {
	addrs, _ := net.InterfaceAddrs()
	for _, a := range addrs {
		if n, ok := a.(*net.IPNet); ok && !n.IP.IsLoopback() && n.IP.To4() != nil {
			return n.IP.String()
		}
	}
	return ""
}

// env reads key and parses it, or returns def when the key is unset or empty.
func env[T any](key string, def T, parse func(string) (T, error)) T {
	s := os.Getenv(key)
	if s == "" {
		return def
	}
	v, err := parse(s)
	if err != nil {
		fatal("invalid " + key + ": " + err.Error())
	}
	return v
}

func str(s string) (string, error)         { return s, nil }
func parseFloat(s string) (float64, error) { return strconv.ParseFloat(s, 64) }

func fatal(msg string) {
	slog.Error(msg)
	os.Exit(1)
}
