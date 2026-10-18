package robot

import (
	"errors"
	"testing"
	"time"
)

var (
	testMap  = Map{Width: 40, Height: 25}
	testSpec = Spec{Model: "t", Speed: 1, DrainWorking: 1, DrainIdle: 0.1, ChargeRate: 5}
	calm     = Chaos{}
	t0       = time.Unix(1_700_000_000, 0)
)

// run steps the robot n seconds with chaos c and returns the last snapshot.
func run(r *Robot, n int, c Chaos) (now time.Time, s Snapshot) {
	r.chaos = c
	now = t0
	for i := 0; i < n; i++ {
		now = now.Add(time.Second)
		s = r.Step(now, time.Second)
	}
	return now, s
}

func TestWorkingDrainsBatteryAndMoves(t *testing.T) {
	r := New("r", testSpec, testMap, calm, 1)
	r.state, r.battery = Working, 80
	start := r.pose
	_, s := run(r, 5, calm)
	if s.Battery >= 80 {
		t.Fatalf("battery did not drain: %.1f", s.Battery)
	}
	if s.Pose == start {
		t.Fatal("robot did not move")
	}
	if s.Seq != 5 {
		t.Fatalf("seq = %d, want 5", s.Seq)
	}
}

func TestLowBatteryReturnsToDockAndCharges(t *testing.T) {
	r := New("r", testSpec, testMap, calm, 1)
	r.state, r.battery = Working, lowBattery-1
	r.pose = Pose{X: 3, Y: 1}
	_, s := run(r, 1, calm)
	if s.State != Returning {
		t.Fatalf("state = %s, want returning", s.State)
	}
	_, s = run(r, 5, calm)
	if s.State != Charging {
		t.Fatalf("state = %s, want charging", s.State)
	}
	before := s.Battery
	_, s = run(r, 2, calm)
	if s.Battery <= before {
		t.Fatalf("battery did not charge: %.1f -> %.1f", before, s.Battery)
	}
}

func TestGoToReachesTarget(t *testing.T) {
	r := New("r", testSpec, testMap, calm, 1)
	r.battery = 100
	r.pose = Pose{X: 20, Y: 3}
	if err := r.Apply(Command{Kind: CmdGoTo, X: 20, Y: 10}); err != nil {
		t.Fatal(err)
	}
	var s Snapshot
	for i := 0; i < 20 && r.target != nil; i++ {
		s = r.Step(t0, time.Second)
	}
	if s.Pose.X != 20 || s.Pose.Y != 10 {
		t.Fatalf("did not reach target, at (%.1f, %.1f)", s.Pose.X, s.Pose.Y)
	}
}

func TestCommandRules(t *testing.T) {
	cases := []struct {
		name   string
		state  State
		cmd    Command
		reject bool
		want   State
	}{
		{"pause working", Working, Command{Kind: CmdPause}, false, Paused},
		{"pause charging", Charging, Command{Kind: CmdPause}, true, Charging},
		{"resume working", Working, Command{Kind: CmdResume}, true, Working},
		{"resume error clears", Error, Command{Kind: CmdResume}, false, Working},
		{"dock in error", Error, Command{Kind: CmdDock}, true, Error},
		{"dock idle", Idle, Command{Kind: CmdDock}, false, Returning},
		{"goto off map", Idle, Command{Kind: CmdGoTo, X: 99, Y: 1}, true, Idle},
		{"goto ok", Idle, Command{Kind: CmdGoTo, X: 1, Y: 1}, false, Working},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := New("r", testSpec, testMap, calm, 1)
			r.state = c.state
			err := r.Apply(c.cmd)
			var rej *RejectedError
			if got := errors.As(err, &rej); got != c.reject {
				t.Fatalf("rejected = %v (%v), want %v", got, err, c.reject)
			}
			if r.state != c.want {
				t.Fatalf("state = %s, want %s", r.state, c.want)
			}
		})
	}
}

func TestPauseThenResumeRestoresState(t *testing.T) {
	r := New("r", testSpec, testMap, calm, 1)
	r.state = Returning
	_ = r.Apply(Command{Kind: CmdPause})
	_ = r.Apply(Command{Kind: CmdResume})
	if r.state != Returning {
		t.Fatalf("state = %s, want returning", r.state)
	}
}

func TestChaos(t *testing.T) {
	t.Run("error", func(t *testing.T) {
		r := New("r", testSpec, testMap, calm, 1)
		r.state, r.battery = Working, 90
		_, s := run(r, 1, Chaos{ErrorRate: 1})
		if s.State != Error || s.Fault == NoFault {
			t.Fatalf("state = %s fault = %s, want error with a fault", s.State, s.Fault)
		}
	})
	t.Run("stuck reports working without moving", func(t *testing.T) {
		r := New("r", testSpec, testMap, calm, 1)
		r.state, r.battery = Working, 90
		start := r.pose
		_, s := run(r, 5, Chaos{StuckRate: 1})
		if s.State != Working || s.Pose != start {
			t.Fatalf("state = %s moved = %v, want working and still", s.State, s.Pose != start)
		}
	})
}
