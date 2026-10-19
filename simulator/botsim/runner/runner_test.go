package runner

import (
	"context"
	"sync/atomic"
	"testing"
	"time"

	"robofleet/simulator/botsim/robot"
)

// fakeVendor counts what the runner hands to a pushing vendor.
type fakeVendor struct{ published, disconnected atomic.Int32 }

func (v *fakeVendor) IDPrefix() string { return "fk" }
func (v *fakeVendor) Spec() robot.Spec { return robot.Spec{Speed: 1} }
func (v *fakeVendor) Connect(*Unit) (func(robot.Snapshot), func(), error) {
	return func(robot.Snapshot) { v.published.Add(1) }, func() { v.disconnected.Add(1) }, nil
}

const tick = 10 * time.Millisecond

func start(t *testing.T, link Link, n int) (*Runner, *fakeVendor, []*Unit) {
	t.Helper()
	v := &fakeVendor{}
	rn := New("t", robot.Map{Width: 10, Height: 10}, tick, 1, robot.Chaos{}, link)
	units, err := rn.Start(v, n)
	if err != nil {
		t.Fatal(err)
	}
	return rn, v, units
}

// eventually polls cond once per tick until it holds or a second has passed.
func eventually(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %s", what)
		}
		time.Sleep(tick)
	}
}

// ticked reports whether every unit has produced at least n readings.
func ticked(units []*Unit, n uint64) bool {
	for _, u := range units {
		if s := u.Latest(); s == nil || s.Seq < n {
			return false
		}
	}
	return true
}

func TestDropoutSilencesRobotAndRefusesCommands(t *testing.T) {
	rn, v, units := start(t, Link{DropoutRate: 1}, 1)
	defer rn.Stop()
	eventually(t, "robot to go offline", func() bool { return ticked(units, 1) && !units[0].Online() })
	if n := v.published.Load(); n != 0 {
		t.Fatalf("published %d readings while offline", n)
	}
	if err := units[0].Send(context.Background(), robot.Command{Kind: robot.CmdPause}); err != ErrUnreachable {
		t.Fatalf("err = %v, want ErrUnreachable", err)
	}
}

func TestDelayHoldsReadingsBack(t *testing.T) {
	rn, v, units := start(t, Link{DelayRate: 1}, 1)
	defer rn.Stop()
	eventually(t, "five ticks", func() bool { return ticked(units, 5) })
	if n := v.published.Load(); n != 0 {
		t.Fatalf("published %d readings, want all held back by at least 1s", n)
	}
}

func TestStopDisconnectsEveryRobot(t *testing.T) {
	rn, v, units := start(t, Link{}, 50)
	eventually(t, "every robot to tick", func() bool { return ticked(units, 1) })
	rn.Stop()
	if n := v.disconnected.Load(); n != 50 {
		t.Fatalf("disconnected %d robots, want 50", n)
	}
	if err := units[0].Send(context.Background(), robot.Command{Kind: robot.CmdPause}); err != ErrStopped {
		t.Fatalf("err after stop = %v, want ErrStopped", err)
	}
}
