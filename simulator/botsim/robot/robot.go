// Package robot is the vendor-agnostic robot model. A Robot is not safe for
// concurrent use. The runner gives each one its own goroutine and that
// goroutine is the only caller of Step and Apply.
package robot

import (
	"errors"
	"fmt"
	"math"
	"math/rand/v2"
	"time"
)

type State int

const (
	Idle State = iota
	Working
	Returning
	Charging
	Paused
	Error
)

func (s State) String() string {
	return [...]string{"idle", "working", "returning", "charging", "paused", "error"}[s]
}

type Fault int

const (
	NoFault Fault = iota
	WheelStuck
	BumperHit
	LocalizationLost
)

func (f Fault) String() string {
	return [...]string{"none", "wheel_stuck", "bumper_hit", "localization_lost"}[f]
}

// Map is the area a robot drives in, in meters. A robot only knows its own map.
type Map struct {
	Width  float64
	Height float64
}

// dock is where every robot charges.
var dock = Pose{X: 1, Y: 1}

type Pose struct {
	X, Y  float64
	Theta float64
}

// Spec holds the physical differences between robot models.
type Spec struct {
	Model        string
	Speed        float64 // m/s
	DrainWorking float64 // battery percent per second while moving
	DrainIdle    float64 // battery percent per second otherwise
	ChargeRate   float64 // battery percent per second on the dock
}

// Chaos is misbehavior of the robot itself. Rates are probabilities per tick.
// Network trouble like dropouts and late messages is the runner's job.
type Chaos struct {
	ErrorRate float64
	StuckRate float64
}

// Snapshot is one reading as the robot itself would report it.
type Snapshot struct {
	ID      string
	Model   string
	Seq     uint64
	Time    time.Time
	Battery float64 // 0..100
	State   State
	Fault   Fault
	Pose    Pose
	Speed   float64
}

type CommandKind int

const (
	CmdPause CommandKind = iota
	CmdResume
	CmdDock
	CmdGoTo
)

type Command struct {
	Kind CommandKind
	X, Y float64
}

// RejectedError is returned when a robot refuses a command it understood.
type RejectedError struct{ Reason string }

func (e *RejectedError) Error() string { return "command rejected: " + e.Reason }

func reject(format string, args ...any) error {
	return &RejectedError{Reason: fmt.Sprintf(format, args...)}
}

// Reason returns the human readable part of a command error.
func Reason(err error) string {
	var r *RejectedError
	if errors.As(err, &r) {
		return r.Reason
	}
	return err.Error()
}

const (
	lowBattery  = 20.0
	fullBattery = 95.0
	arriveDist  = 0.3
)

type Robot struct {
	id    string
	spec  Spec
	area  Map
	chaos Chaos
	rng   *rand.Rand

	seq     uint64
	state   State
	fault   Fault
	pose    Pose
	battery float64

	target    *Pose     // final destination while working or returning
	resumeTo  State     // state to restore after Paused
	idleUntil time.Time // idle robots start working again after this
	errUntil  time.Time // errors clear on their own after this
	stuckTill time.Time // silently stuck, reports working but does not move
}

func New(id string, spec Spec, area Map, chaos Chaos, seed int64) *Robot {
	rng := rand.New(rand.NewPCG(uint64(seed), 0))
	return &Robot{
		id:      id,
		spec:    spec,
		area:    area,
		chaos:   chaos,
		rng:     rng,
		state:   Idle,
		battery: 40 + rng.Float64()*60,
		pose: Pose{
			X: rng.Float64() * area.Width,
			Y: rng.Float64() * area.Height,
		},
	}
}

// Step advances the simulation by dt and returns the reading for now.
func (r *Robot) Step(now time.Time, dt time.Duration) Snapshot {
	sec := dt.Seconds()
	r.rollChaos(now)

	moving := false
	switch r.state {
	case Idle:
		if now.After(r.idleUntil) {
			r.state, r.target = Working, nil
		}
	case Working, Returning:
		if r.battery <= 0 || now.Before(r.stuckTill) {
			break
		}
		if r.state == Working && r.battery < lowBattery {
			r.goDock()
		}
		if r.target == nil {
			r.target = r.randomTarget()
		}
		moving = true
		if r.moveToward(*r.target, r.spec.Speed*sec) {
			r.arrived(now)
		}
	case Charging:
		r.battery += r.spec.ChargeRate * sec
		if r.battery >= fullBattery {
			r.state = Idle
			r.idleUntil = now.Add(r.jitter(5, 15))
		}
	case Error:
		if now.After(r.errUntil) {
			r.fault = NoFault
			r.state = Working
		}
	}

	if moving {
		r.battery -= r.spec.DrainWorking * sec
	} else if r.state != Charging {
		r.battery -= r.spec.DrainIdle * sec
	}
	r.battery = max(0, min(100, r.battery))

	r.seq++
	snap := Snapshot{
		ID:      r.id,
		Model:   r.spec.Model,
		Seq:     r.seq,
		Time:    now,
		Battery: r.battery,
		State:   r.state,
		Fault:   r.fault,
		Pose:    r.pose,
	}
	if moving {
		snap.Speed = r.spec.Speed
	}
	return snap
}

func (r *Robot) rollChaos(now time.Time) {
	if r.state != Working && r.state != Returning {
		return
	}
	if r.roll(r.chaos.ErrorRate) {
		r.state = Error
		r.fault = Fault(1 + r.rng.IntN(3))
		r.errUntil = now.Add(r.jitter(20, 90))
		return
	}
	if r.state == Working && now.After(r.stuckTill) && r.roll(r.chaos.StuckRate) {
		r.stuckTill = now.Add(r.jitter(60, 180))
	}
}

// Apply executes a command or returns a *RejectedError.
func (r *Robot) Apply(cmd Command) error {
	switch cmd.Kind {
	case CmdPause:
		switch r.state {
		case Working, Returning, Idle:
			r.resumeTo = r.state
			r.state = Paused
			return nil
		}
		return reject("cannot pause while %s", r.state)
	case CmdResume:
		switch r.state {
		case Paused:
			r.state = r.resumeTo
			return nil
		case Error:
			r.fault = NoFault
			r.state = Working
			return nil
		}
		return reject("cannot resume while %s", r.state)
	case CmdDock:
		switch r.state {
		case Error:
			return reject("clear the %s fault first", r.fault)
		case Charging, Returning:
			return reject("already %s", r.state)
		}
		r.goDock()
		return nil
	case CmdGoTo:
		if r.state == Error || r.state == Charging {
			return reject("cannot navigate while %s", r.state)
		}
		if cmd.X < 0 || cmd.X > r.area.Width || cmd.Y < 0 || cmd.Y > r.area.Height {
			return reject("target (%.1f, %.1f) is outside the map", cmd.X, cmd.Y)
		}
		r.target = &Pose{X: cmd.X, Y: cmd.Y}
		r.state = Working
		return nil
	}
	return reject("unknown command %d", cmd.Kind)
}

func (r *Robot) goDock() {
	d := dock
	r.target = &d
	r.state = Returning
}

func (r *Robot) arrived(now time.Time) {
	r.target = nil
	if r.state == Returning {
		r.state = Charging
		return
	}
	if r.rng.Float64() < 0.3 {
		r.state = Idle
		r.idleUntil = now.Add(r.jitter(5, 20))
	}
}

func (r *Robot) randomTarget() *Pose {
	return &Pose{X: r.rng.Float64() * r.area.Width, Y: r.rng.Float64() * r.area.Height}
}

// moveToward moves up to step meters toward dst and reports arrival.
func (r *Robot) moveToward(dst Pose, step float64) bool {
	dx, dy := dst.X-r.pose.X, dst.Y-r.pose.Y
	dist := math.Hypot(dx, dy)
	if dist <= max(step, arriveDist) {
		r.pose.X, r.pose.Y = dst.X, dst.Y
		return true
	}
	r.pose.X += dx / dist * step
	r.pose.Y += dy / dist * step
	r.pose.Theta = math.Atan2(dy, dx)
	return false
}

func (r *Robot) roll(p float64) bool { return p > 0 && r.rng.Float64() < p }

func (r *Robot) jitter(minSec, maxSec int) time.Duration {
	return time.Duration(minSec+r.rng.IntN(maxSec-minSec+1)) * time.Second
}
