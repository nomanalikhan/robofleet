// Package runner runs one goroutine per robot and simulates the robot's
// network link. Vendors plug in to decide how readings leave the simulator and
// how commands come in.
package runner

import (
	"context"
	"errors"
	"fmt"
	"hash/fnv"
	"math/rand/v2"
	"sync"
	"sync/atomic"
	"time"

	"olivaw/simulator/botsim/robot"
)

// Vendor is the transport side of one robot brand.
type Vendor interface {
	// IDPrefix is the short code used in robot serials, for example "rv".
	IDPrefix() string
	Spec() robot.Spec
	// Connect wires one robot to the vendor's transport before its first tick.
	// publish is called with every reading the link delivers. disconnect runs
	// after the robot has stopped. Either may be nil, for example publish for
	// vendors whose robots are polled. A non-nil error means the robot could
	// not be wired up and must not run.
	Connect(u *Unit) (publish func(robot.Snapshot), disconnect func(), err error)
}

// Link is chaos on the robot's connection rather than its behavior. Rates are
// chances per robot per tick.
type Link struct {
	DropoutRate float64 // robot goes silent for 15 to 90s
	DelayRate   float64 // one reading is delivered 1 to 4s late
}

// commandTimeout bounds how long Send waits for a robot to answer.
const commandTimeout = 5 * time.Second

var (
	ErrStopped     = errors.New("robot is not running")
	ErrUnreachable = errors.New("robot is unreachable")
)

type cmdReq struct {
	cmd   robot.Command
	reply chan error
}

// Unit is a running robot. Its methods are safe for concurrent use.
type Unit struct {
	ID     string
	cmds   chan cmdReq
	latest atomic.Pointer[robot.Snapshot]
	online atomic.Bool
	stop   <-chan struct{}
}

// Latest returns the most recent reading, or nil before the first tick.
func (u *Unit) Latest() *robot.Snapshot { return u.latest.Load() }

// Online is false while the robot's link is down.
func (u *Unit) Online() bool { return u.online.Load() }

// Send hands a command to the robot's goroutine and waits for the result.
func (u *Unit) Send(ctx context.Context, cmd robot.Command) error {
	select {
	case <-u.stop:
		return ErrStopped
	default:
	}
	if !u.Online() {
		return ErrUnreachable
	}
	ctx, cancel := context.WithTimeout(ctx, commandTimeout)
	defer cancel()
	req := cmdReq{cmd: cmd, reply: make(chan error, 1)}
	select {
	case u.cmds <- req:
	case <-u.stop:
		return ErrStopped
	case <-ctx.Done():
		return ctx.Err()
	}
	select {
	case err := <-req.reply:
		return err
	case <-u.stop:
		return ErrStopped
	case <-ctx.Done():
		return ctx.Err()
	}
}

// Runner is built once at startup. Start and Stop are not safe for concurrent
// use, which is fine because only main calls them.
type Runner struct {
	simID string // namespaces serials so two simulators do not collide
	area  robot.Map
	tick  time.Duration
	seed  int64
	chaos robot.Chaos
	link  Link

	ctx     context.Context
	cancel  context.CancelFunc
	wg      sync.WaitGroup
	serials map[string]bool
}

// New builds a runner. tick must be positive.
func New(simID string, area robot.Map, tick time.Duration, seed int64, chaos robot.Chaos, link Link) *Runner {
	if tick <= 0 {
		panic("runner: tick must be positive")
	}
	ctx, cancel := context.WithCancel(context.Background())
	return &Runner{
		simID: simID, area: area, tick: tick, seed: seed, chaos: chaos, link: link,
		ctx: ctx, cancel: cancel, serials: map[string]bool{},
	}
}

// Start launches n robots of one vendor and returns them. Serials are
// deterministic, so a restarted simulator brings back the same robots. It
// stops at the first robot that fails to connect and returns that error.
func (rn *Runner) Start(v Vendor, n int) ([]*Unit, error) {
	out := make([]*Unit, 0, n)
	for i := 1; i <= n; i++ {
		id := rn.serial(v, i)
		u := &Unit{ID: id, cmds: make(chan cmdReq), stop: rn.ctx.Done()}
		u.online.Store(true)
		r := robot.New(id, v.Spec(), rn.area, rn.chaos, rn.seed^idHash(id))
		publish, disconnect, err := v.Connect(u)
		if err != nil {
			return out, fmt.Errorf("connect %s: %w", id, err)
		}
		rn.wg.Add(1)
		go rn.run(u, r, publish, disconnect)
		out = append(out, u)
	}
	return out, nil
}

// Stop halts every robot at once and waits for them to disconnect.
func (rn *Runner) Stop() {
	rn.cancel()
	rn.wg.Wait()
}

func (rn *Runner) run(u *Unit, r *robot.Robot, publish func(robot.Snapshot), disconnect func()) {
	defer rn.wg.Done()
	if disconnect != nil {
		defer disconnect()
	}
	link := rand.New(rand.NewPCG(uint64(rn.seed^idHash(u.ID+"/link")), 0))
	var offlineUntil time.Time

	// Spread robots across the tick so they do not all report at once.
	select {
	case <-time.After(time.Duration(idHash(u.ID) % int64(rn.tick))):
	case <-rn.ctx.Done():
		return
	}
	t := time.NewTicker(rn.tick)
	defer t.Stop()
	last := time.Now()
	for {
		select {
		case <-rn.ctx.Done():
			return
		case req := <-u.cmds:
			req.reply <- r.Apply(req.cmd)
		case now := <-t.C:
			snap := r.Step(now, now.Sub(last))
			last = now
			u.latest.Store(&snap)

			if now.After(offlineUntil) && roll(link, rn.link.DropoutRate) {
				offlineUntil = now.Add(jitter(link, 15, 90))
			}
			online := !now.Before(offlineUntil)
			u.online.Store(online)
			if !online || publish == nil {
				continue
			}
			if roll(link, rn.link.DelayRate) {
				// Stop waits for late readings so none is published after
				// the robot has disconnected.
				rn.wg.Add(1)
				time.AfterFunc(jitter(link, 1, 4), func() {
					defer rn.wg.Done()
					select {
					case <-rn.ctx.Done():
						return
					default:
					}
					publish(snap)
				})
				continue
			}
			publish(snap)
		}
	}
}

// serial returns the serial of the n-th robot of a vendor, like "rv-3f9a21".
// It is a hash so it says nothing about where the robot is deployed.
func (rn *Runner) serial(v Vendor, n int) string {
	for salt := 0; ; salt++ {
		h := idHash(fmt.Sprintf("%s/%s/%d/%d", rn.simID, v.IDPrefix(), n, salt))
		id := fmt.Sprintf("%s-%06x", v.IDPrefix(), h&0xffffff)
		if !rn.serials[id] {
			rn.serials[id] = true
			return id
		}
	}
}

func roll(rng *rand.Rand, p float64) bool { return p > 0 && rng.Float64() < p }

func jitter(rng *rand.Rand, minSec, maxSec int) time.Duration {
	return time.Duration(minSec+rng.IntN(maxSec-minSec+1)) * time.Second
}

func idHash(s string) int64 {
	h := fnv.New64a()
	h.Write([]byte(s))
	return int64(h.Sum64() & (1<<62 - 1))
}
