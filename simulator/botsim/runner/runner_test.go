package runner

import (
	"context"
	"sync/atomic"
	"testing"
	"time"

	"olivaw/simulator/botsim/robot"
)

// fakeVendor counts what the runner hands to a pushing vendor.
type fakeVendor struct{ published, disconnected atomic.Int32 }

func (v *fakeVendor) IDPrefix() string { return "fk" }
func (v *fakeVendor) Spec() robot.Spec { return robot.Spec{Speed: 1} }
func (v *fakeVendor) Connect(*Unit) (func(robot.Snapshot), func()) {
	return func(robot.Snapshot) { v.published.Add(1) }, func() { v.disconnected.Add(1) }
}

const tick = 10 * time.Millisecond

func start(link Link, n int) (*Runner, *fakeVendor, []*Unit) {
	v := &fakeVendor{}
	rn := New("t", robot.Map{Width: 10, Height: 10}, tick, 1, robot.Chaos{}, link)
	return rn, v, rn.Start(v, n)
}

func TestDropoutSilencesRobotAndRefusesCommands(t *testing.T) {
	rn, v, units := start(Link{DropoutRate: 1}, 1)
	defer rn.Stop()
	time.Sleep(5 * tick)
	if units[0].Online() {
		t.Fatal("robot should be offline")
	}
	if n := v.published.Load(); n != 0 {
		t.Fatalf("published %d readings while offline", n)
	}
	if err := units[0].Send(context.Background(), robot.Command{Kind: robot.CmdPause}); err != ErrUnreachable {
		t.Fatalf("err = %v, want ErrUnreachable", err)
	}
}

func TestDelayHoldsReadingsBack(t *testing.T) {
	rn, v, _ := start(Link{DelayRate: 1}, 1)
	defer rn.Stop()
	time.Sleep(5 * tick)
	if n := v.published.Load(); n != 0 {
		t.Fatalf("published %d readings, want all held back by at least 1s", n)
	}
}

func TestStopDisconnectsEveryRobot(t *testing.T) {
	rn, v, units := start(Link{}, 50)
	time.Sleep(3 * tick)
	rn.Stop()
	if n := v.disconnected.Load(); n != 50 {
		t.Fatalf("disconnected %d robots, want 50", n)
	}
	if err := units[0].Send(context.Background(), robot.Command{Kind: robot.CmdPause}); err != ErrStopped {
		t.Fatalf("err after stop = %v, want ErrStopped", err)
	}
}
