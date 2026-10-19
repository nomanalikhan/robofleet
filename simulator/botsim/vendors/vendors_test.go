package vendors_test

import (
	"encoding/json"
	"regexp"
	"testing"
	"time"

	"robofleet/simulator/botsim/robot"
	"robofleet/simulator/botsim/runner"
	"robofleet/simulator/botsim/vendors/cleanix"
	"robofleet/simulator/botsim/vendors/rovo"
)

var snap = robot.Snapshot{
	ID: "x-1", Model: "m", Seq: 7, Time: time.UnixMilli(1760700000123),
	Battery: 42.4, State: robot.Error, Fault: robot.BumperHit,
	Pose: robot.Pose{X: 12.345, Y: 7.9},
}

func TestRovoTelemetryUnits(t *testing.T) {
	got := rovo.ToTelemetry(snap)
	if got.Battery != 42 || got.Status != "ERROR" || got.ErrorCode != 102 {
		t.Fatalf("battery/status/code = %d/%s/%d", got.Battery, got.Status, got.ErrorCode)
	}
	if got.Pose.X != 12.35 || got.Timestamp != 1760700000123 {
		t.Fatalf("pose/ts = %+v/%d", got.Pose, got.Timestamp)
	}
}

func TestRovoGoTo(t *testing.T) {
	var c rovo.Command
	_ = json.Unmarshal([]byte(`{"action":"GOTO","params":{"x":3,"y":4}}`), &c)
	cmd, err := rovo.ToCommand(c)
	if err != nil || cmd.Kind != robot.CmdGoTo || cmd.X != 3 || cmd.Y != 4 {
		t.Fatalf("cmd = %+v err = %v", cmd, err)
	}
}

func TestCleanixStatusUnits(t *testing.T) {
	got := cleanix.ToStatus(snap)
	if got.BatteryLevel != 0.424 || got.WorkState != "fault" || got.Fault == nil || got.Fault.Code != "E102" {
		t.Fatalf("status = %+v", got)
	}
	if got.Location.XCm != 1235 || got.TS != "2025-10-17T11:20:00.123Z" {
		t.Fatalf("location/ts = %+v/%s", got.Location, got.TS)
	}
}

func TestSerialsSurviveRestart(t *testing.T) {
	serials := func() []string {
		sim := runner.New("t", robot.Map{Width: 10, Height: 10}, time.Hour, 1, robot.Chaos{}, runner.Link{})
		defer sim.Stop()
		units, err := sim.Start(cleanix.New("127.0.0.1:0"), 3)
		if err != nil {
			t.Fatal(err)
		}
		var out []string
		for _, u := range units {
			out = append(out, u.ID)
		}
		return out
	}
	before, after := serials(), serials()
	for i := range before {
		if !regexp.MustCompile(`^cx-[0-9a-f]{6}$`).MatchString(before[i]) {
			t.Fatalf("serial %q does not look like cx-xxxxxx", before[i])
		}
		if before[i] != after[i] {
			t.Fatalf("serial changed after restart: %s -> %s", before[i], after[i])
		}
	}
}
