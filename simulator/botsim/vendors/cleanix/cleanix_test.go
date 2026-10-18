package cleanix

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"olivaw/simulator/botsim/robot"
	"olivaw/simulator/botsim/runner"
)

func TestRobotAPI(t *testing.T) {
	v := New("127.0.0.1:0")
	sim := runner.New("t", robot.Map{Width: 10, Height: 10}, 10*time.Millisecond, 1, robot.Chaos{}, runner.Link{})
	u := sim.Start(v, 1)[0]
	defer sim.Stop()
	for u.Latest() == nil {
		time.Sleep(5 * time.Millisecond)
	}
	srv := httptest.NewServer(v.handler(u))
	defer srv.Close()
	base := srv.URL + BasePath

	var info Info
	get(t, base+"/info", &info)
	var st Status
	get(t, base+"/status", &st)
	if info.Serial != u.ID || st.Serial != u.ID {
		t.Fatalf("robot answered as %q / %q, want %q", info.Serial, st.Serial, u.ID)
	}

	for _, want := range []int{http.StatusAccepted, http.StatusConflict} {
		res, err := http.Post(base+"/commands", "application/json", strings.NewReader(`{"command":"go_home"}`))
		if err != nil || res.StatusCode != want {
			t.Fatalf("go_home = %v %v, want %d", res.StatusCode, err, want)
		}
	}
}

func get(t *testing.T, url string, out any) {
	t.Helper()
	res, err := http.Get(url)
	if err != nil || res.StatusCode != http.StatusOK {
		t.Fatalf("GET %s: %v %v", url, res, err)
	}
	defer res.Body.Close()
	if err := json.NewDecoder(res.Body).Decode(out); err != nil {
		t.Fatal(err)
	}
}
