// Package rovo simulates the Rovo vendor protocol. Every robot holds its own
// MQTT connection, pushes telemetry once per tick and takes commands on its
// own topic. See the wire formats in README.md.
package rovo

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"time"

	mqtt "github.com/eclipse/paho.mqtt.golang"

	"olivaw/simulator/botsim/robot"
	"olivaw/simulator/botsim/runner"
)

type Telemetry struct {
	RobotID   string  `json:"robotId"`
	Model     string  `json:"model"`
	Timestamp int64   `json:"timestamp"`
	Seq       uint64  `json:"seq"`
	Battery   int     `json:"battery"`
	Status    string  `json:"status"`
	ErrorCode int     `json:"errorCode"`
	Pose      Pose    `json:"pose"`
	Speed     float64 `json:"speed"`
}

type Pose struct {
	X     float64 `json:"x"`
	Y     float64 `json:"y"`
	Theta float64 `json:"theta"`
}

type Command struct {
	CmdID  string `json:"cmdId"`
	Action string `json:"action"`
	Params struct {
		X float64 `json:"x"`
		Y float64 `json:"y"`
	} `json:"params"`
}

type Ack struct {
	CmdID     string `json:"cmdId"`
	Result    string `json:"result"`
	Reason    string `json:"reason,omitempty"`
	Timestamp int64  `json:"timestamp"`
}

var statuses = map[robot.State]string{
	robot.Idle:      "IDLE",
	robot.Working:   "WORKING",
	robot.Returning: "RETURNING",
	robot.Charging:  "CHARGING",
	robot.Paused:    "PAUSED",
	robot.Error:     "ERROR",
}

var errorCodes = map[robot.Fault]int{
	robot.NoFault:          0,
	robot.WheelStuck:       101,
	robot.BumperHit:        102,
	robot.LocalizationLost: 103,
}

func ToTelemetry(s robot.Snapshot) Telemetry {
	return Telemetry{
		RobotID:   s.ID,
		Model:     s.Model,
		Timestamp: s.Time.UnixMilli(),
		Seq:       s.Seq,
		Battery:   int(math.Round(s.Battery)),
		Status:    statuses[s.State],
		ErrorCode: errorCodes[s.Fault],
		Pose: Pose{
			X:     round(s.Pose.X, 2),
			Y:     round(s.Pose.Y, 2),
			Theta: round(s.Pose.Theta, 2),
		},
		Speed: s.Speed,
	}
}

func ToCommand(c Command) (robot.Command, error) {
	switch c.Action {
	case "PAUSE":
		return robot.Command{Kind: robot.CmdPause}, nil
	case "RESUME":
		return robot.Command{Kind: robot.CmdResume}, nil
	case "DOCK":
		return robot.Command{Kind: robot.CmdDock}, nil
	case "GOTO":
		return robot.Command{Kind: robot.CmdGoTo, X: c.Params.X, Y: c.Params.Y}, nil
	}
	return robot.Command{}, fmt.Errorf("unknown action %q", c.Action)
}

type Vendor struct{ brokerURL string }

func New(brokerURL string) *Vendor { return &Vendor{brokerURL: brokerURL} }

func (v *Vendor) IDPrefix() string { return "rv" }
func (v *Vendor) Spec() robot.Spec {
	return robot.Spec{Model: "Rovo D2", Speed: 0.8, DrainWorking: 0.12, DrainIdle: 0.02, ChargeRate: 0.6}
}

// Connect gives the robot its own MQTT client, like a real robot would have.
func (v *Vendor) Connect(u *runner.Unit) (func(robot.Snapshot), func()) {
	online := topic(u.ID, "online")
	opts := mqtt.NewClientOptions().
		AddBroker(v.brokerURL).
		SetClientID(u.ID).
		SetCleanSession(true).
		SetAutoReconnect(true).
		SetConnectRetry(true).
		SetConnectRetryInterval(2*time.Second).
		SetOrderMatters(false).
		SetWill(online, "0", 1, true)
	opts.SetOnConnectHandler(func(c mqtt.Client) {
		c.Publish(online, 1, true, "1")
		c.Subscribe(topic(u.ID, "cmd"), 1, func(c mqtt.Client, m mqtt.Message) {
			handleCommand(c, u, m.Payload())
		})
	})
	c := mqtt.NewClient(opts)
	c.Connect() // retries in the background until the broker is up

	telemetry := topic(u.ID, "telemetry")
	publish := func(s robot.Snapshot) {
		if !c.IsConnectionOpen() {
			return
		}
		body, _ := json.Marshal(ToTelemetry(s))
		c.Publish(telemetry, 0, false, body)
	}
	disconnect := func() {
		// A robot that shuts down says goodbye, unlike a dropout.
		c.Publish(online, 1, true, "0").WaitTimeout(time.Second)
		c.Disconnect(250)
	}
	return publish, disconnect
}

func handleCommand(c mqtt.Client, u *runner.Unit, payload []byte) {
	var in Command
	err := json.Unmarshal(payload, &in)
	if err == nil {
		err = apply(u, in)
	}
	if errors.Is(err, runner.ErrUnreachable) {
		return // an offline robot never sees the command, so it cannot ack
	}
	ack := Ack{CmdID: in.CmdID, Result: "OK", Timestamp: time.Now().UnixMilli()}
	if err != nil {
		ack.Result = "REJECTED"
		ack.Reason = robot.Reason(err)
	}
	body, _ := json.Marshal(ack)
	c.Publish(topic(u.ID, "cmd/ack"), 1, false, body)
	slog.Info("rovo command", "robot", u.ID, "cmd", in.Action, "result", ack.Result, "reason", ack.Reason)
}

func apply(u *runner.Unit, in Command) error {
	cmd, err := ToCommand(in)
	if err != nil {
		return err
	}
	return u.Send(context.Background(), cmd)
}

func topic(id, leaf string) string { return "rovo/" + id + "/" + leaf }

func round(f float64, places int) float64 {
	p := math.Pow10(places)
	return math.Round(f*p) / p
}
