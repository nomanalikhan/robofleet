// Package cleanix simulates the Cleanix vendor protocol. Robots push nothing.
// Every robot runs its own small HTTP server that serves its latest status and
// accepts commands. See the wire formats in README.md.
package cleanix

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"net"
	"net/http"
	"sync/atomic"
	"time"

	"olivaw/simulator/botsim/robot"
	"olivaw/simulator/botsim/runner"
)

const BasePath = "/api/v1"

type Status struct {
	Serial       string   `json:"serial"`
	Model        string   `json:"model"`
	TS           string   `json:"ts"`
	BatteryLevel float64  `json:"battery_level"`
	WorkState    string   `json:"work_state"`
	Fault        *Fault   `json:"fault"`
	Location     Location `json:"location"`
}

type Fault struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type Location struct {
	XCm        int `json:"x_cm"`
	YCm        int `json:"y_cm"`
	HeadingDeg int `json:"heading_deg"`
}

type Command struct {
	Command string `json:"command"`
	Target  *struct {
		XCm int `json:"x_cm"`
		YCm int `json:"y_cm"`
	} `json:"target"`
}

var workStates = map[robot.State]string{
	robot.Idle:      "idle",
	robot.Working:   "cleaning",
	robot.Returning: "returning_home",
	robot.Charging:  "docked_charging",
	robot.Paused:    "paused",
	robot.Error:     "fault",
}

var faults = map[robot.Fault]Fault{
	robot.WheelStuck:       {Code: "E201", Message: "wheel stuck"},
	robot.BumperHit:        {Code: "E102", Message: "bumper hit"},
	robot.LocalizationLost: {Code: "E310", Message: "localization lost"},
}

func ToStatus(s robot.Snapshot) Status {
	out := Status{
		Serial:       s.ID,
		Model:        s.Model,
		TS:           s.Time.UTC().Format("2006-01-02T15:04:05.000Z07:00"),
		BatteryLevel: math.Round(s.Battery*10) / 1000,
		WorkState:    workStates[s.State],
		Location: Location{
			XCm:        int(math.Round(s.Pose.X * 100)),
			YCm:        int(math.Round(s.Pose.Y * 100)),
			HeadingDeg: (int(math.Round(s.Pose.Theta*180/math.Pi)) + 360) % 360,
		},
	}
	if f, ok := faults[s.Fault]; ok {
		out.Fault = &f
	}
	return out
}

func ToCommand(c Command) (robot.Command, error) {
	switch c.Command {
	case "pause":
		return robot.Command{Kind: robot.CmdPause}, nil
	case "resume":
		return robot.Command{Kind: robot.CmdResume}, nil
	case "go_home":
		return robot.Command{Kind: robot.CmdDock}, nil
	case "navigate":
		if c.Target == nil {
			return robot.Command{}, fmt.Errorf("navigate needs a target")
		}
		return robot.Command{
			Kind: robot.CmdGoTo,
			X:    float64(c.Target.XCm) / 100,
			Y:    float64(c.Target.YCm) / 100,
		}, nil
	}
	return robot.Command{}, fmt.Errorf("unknown command %q", c.Command)
}

// Info identifies a robot to whoever probes its address.
type Info struct {
	Serial string `json:"serial"`
	Model  string `json:"model"`
}

// Accepted is the reply to a command the robot took.
type Accepted struct {
	TaskID   string `json:"task_id"`
	Accepted bool   `json:"accepted"`
}

// Vendor runs one Cleanix robot per process, like one robot per machine on a
// real site. Scale out with more containers, each with its own IP.
type Vendor struct {
	addr  string
	tasks atomic.Uint64
}

// New returns a vendor whose robot listens on addr, for example ":8080".
func New(addr string) *Vendor { return &Vendor{addr: addr} }

func (v *Vendor) IDPrefix() string { return "cx" }
func (v *Vendor) Spec() robot.Spec {
	return robot.Spec{Model: "Cleanix S7", Speed: 0.4, DrainWorking: 0.15, DrainIdle: 0.02, ChargeRate: 0.5}
}

// Connect gives the robot its own HTTP server. Cleanix robots are polled, so
// there is nothing to publish.
func (v *Vendor) Connect(u *runner.Unit) (func(robot.Snapshot), func(), error) {
	ln, err := net.Listen("tcp", v.addr)
	if err != nil {
		return nil, nil, fmt.Errorf("cleanix robot %s cannot listen on %s: %w", u.ID, v.addr, err)
	}
	slog.Info("cleanix robot listening", "robot", u.ID, "addr", ln.Addr().String())
	srv := &http.Server{Handler: v.handler(u), ReadHeaderTimeout: 5 * time.Second}
	go func() {
		if err := srv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
			slog.Error("cleanix robot server stopped", "robot", u.ID, "err", err)
		}
	}()
	disconnect := func() {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		defer cancel()
		_ = srv.Shutdown(ctx)
	}
	return nil, disconnect, nil
}

// handler serves one robot's API.
func (v *Vendor) handler(u *runner.Unit) http.Handler {
	spec := v.Spec()
	mux := http.NewServeMux()
	mux.HandleFunc("GET "+BasePath+"/info", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, Info{Serial: u.ID, Model: spec.Model})
	})
	mux.HandleFunc("GET "+BasePath+"/status", func(w http.ResponseWriter, _ *http.Request) {
		s := u.Latest()
		if s == nil || !u.Online() {
			fail(w, http.StatusServiceUnavailable, "robot unreachable")
			return
		}
		writeJSON(w, http.StatusOK, ToStatus(*s))
	})
	mux.HandleFunc("POST "+BasePath+"/commands", func(w http.ResponseWriter, r *http.Request) {
		v.command(w, r, u)
	})
	return mux
}

func (v *Vendor) command(w http.ResponseWriter, r *http.Request, u *runner.Unit) {
	var in Command
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		fail(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	cmd, err := ToCommand(in)
	if err != nil {
		fail(w, http.StatusBadRequest, err.Error())
		return
	}
	var rejected *robot.RejectedError
	switch err = u.Send(r.Context(), cmd); {
	case errors.As(err, &rejected):
		slog.Info("cleanix command", "robot", u.ID, "cmd", in.Command, "result", "rejected", "reason", rejected.Reason)
		fail(w, http.StatusConflict, rejected.Reason)
	case err != nil:
		fail(w, http.StatusServiceUnavailable, "robot unreachable")
	default:
		task := fmt.Sprintf("cx-task-%06d", v.tasks.Add(1))
		slog.Info("cleanix command", "robot", u.ID, "cmd", in.Command, "result", "accepted", "task", task)
		writeJSON(w, http.StatusAccepted, Accepted{TaskID: task, Accepted: true})
	}
}

func fail(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
