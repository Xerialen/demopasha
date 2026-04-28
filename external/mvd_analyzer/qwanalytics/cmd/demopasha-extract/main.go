// demopasha-extract reads an MVD demo and emits a dashboard-compatible
// JSON document in the same shape as `mimer --dump-analysis`, so the
// demopasha dashboard's glue server can consume it as a drop-in
// replacement for the mimer binary.
//
// The schema match is intentional: demopasha/phase0/glue-server.js
// already understands the mimer shape, so swapping the parser
// underneath does not require dashboard changes. See
// demopasha/docs/superpowers/specs/2026-04-28-mvd-analyzer-integration.md
// for the integration design.
//
// Usage:
//
//	demopasha-extract <demo.mvd | demo.mvd.gz>           # lenient parse
//	demopasha-extract -strict <demo.mvd>                 # hard-fail on any unknown opcode
//	demopasha-extract -snap-hz 10 <demo>                 # 10 snapshots/s (default)
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/mvd-analyzer/qwdemo/events"
	"github.com/mvd-analyzer/qwdemo/mvd"
	"github.com/mvd-analyzer/qwdemo/parser"
	mvdsource "github.com/mvd-analyzer/qwdemo/source/mvd"
)

const (
	flagBitRL   = 1 << 0
	flagBitLG   = 1 << 1
	flagBitQuad = 1 << 2
	flagBitPent = 1 << 3
)

// playerState tracks the per-player data we need to emit for a snapshot.
type playerState struct {
	num    int
	name   string
	team   string
	origin [3]float32
	angles [3]float32
	health int
	armor  int
	items  int
	hasPos bool
	alive  bool
}

func (s *playerState) flags() int {
	f := 0
	if s.items&events.ITRocketLauncher != 0 {
		f |= flagBitRL
	}
	if s.items&events.ITLightning != 0 {
		f |= flagBitLG
	}
	if s.items&events.ITQuad != 0 {
		f |= flagBitQuad
	}
	if s.items&events.ITInvulnerability != 0 {
		f |= flagBitPent
	}
	return f
}

type snapshotEntry [10]interface{}

type snapshot struct {
	T float64         `json:"t"`
	P []snapshotEntry `json:"p"`
}

type playerMeta struct {
	Num  int    `json:"num"`
	Name string `json:"name"`
	Team string `json:"team"`
}

type positionTimeline struct {
	Players        []playerMeta             `json:"players"`
	Snapshots      []snapshot               `json:"snapshots"`
	ItemEvents     []map[string]interface{} `json:"item_events"`
	StaticItems    []map[string]interface{} `json:"static_items"`
	PowerupEvents  []map[string]interface{} `json:"powerup_events"`
	QualityMetrics map[string]interface{}   `json:"quality_metrics"`
}

type killEvent struct {
	Time      float64    `json:"time"`
	Killer    string     `json:"killer"`
	Victim    string     `json:"victim"`
	Weapon    string     `json:"weapon"`
	KillerPos [3]float32 `json:"killer_pos"`
	VictimPos [3]float32 `json:"victim_pos"`
}

type dashboardJSON struct {
	Map              string                 `json:"map"`
	PositionTimeline positionTimeline       `json:"position_timeline"`
	KillEvents       []killEvent            `json:"kill_events"`
	DataQuality      map[string]interface{} `json:"data_quality"`
}

type warningSummary struct {
	Type    string  `json:"type"`
	Time    float64 `json:"time"`
	Message string  `json:"message"`
}

func main() {
	strict := flag.Bool("strict", false, "fail on any parser warning (demopasha invariant #1)")
	snapHz := flag.Float64("snap-hz", 10.0, "snapshot rate in Hz (default 10 = 100ms buckets)")
	pretty := flag.Bool("pretty", false, "pretty-print JSON")
	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: demopasha-extract [options] <demo.mvd | demo.mvd.gz>\n\n")
		flag.PrintDefaults()
	}
	flag.Parse()

	if flag.NArg() != 1 {
		flag.Usage()
		os.Exit(2)
	}
	if *snapHz <= 0 {
		fmt.Fprintln(os.Stderr, "demopasha-extract: -snap-hz must be > 0")
		os.Exit(2)
	}

	if err := run(flag.Arg(0), os.Stdout, *strict, *snapHz, *pretty); err != nil {
		fmt.Fprintln(os.Stderr, "demopasha-extract:", err)
		os.Exit(1)
	}
}

func run(path string, w io.Writer, strict bool, snapHz float64, pretty bool) error {
	src, err := mvdsource.Open(path)
	if err != nil {
		return fmt.Errorf("open %s: %w", path, err)
	}
	defer src.Close()

	p := src.Parser()
	if strict {
		p.SetStrictMode(true)
	} else {
		p.SetDiagnosticMode(true)
	}

	out := dashboardJSON{
		Map: "unknown",
		PositionTimeline: positionTimeline{
			Players:       []playerMeta{},
			Snapshots:     []snapshot{},
			ItemEvents:    []map[string]interface{}{},
			StaticItems:   []map[string]interface{}{},
			PowerupEvents: []map[string]interface{}{},
		},
		KillEvents: []killEvent{},
	}

	players := make(map[int]*playerState)
	bucketDur := 1.0 / snapHz
	var nextBucketEdge float64 = bucketDur
	var lastEventTime float64

	flushBucket := func(at float64) {
		entries := make([]snapshotEntry, 0, len(players))
		// Order by player num for stable output
		nums := make([]int, 0, len(players))
		for n := range players {
			nums = append(nums, n)
		}
		sort.Ints(nums)
		for _, n := range nums {
			ps := players[n]
			if ps == nil || !ps.hasPos {
				continue
			}
			entries = append(entries, snapshotEntry{
				ps.num,
				roundCoord(ps.origin[0]),
				roundCoord(ps.origin[1]),
				roundCoord(ps.origin[2]),
				boolToInt(ps.alive),
				ps.health,
				ps.armor,
				ps.flags(),
				int(math.Round(float64(ps.angles[0]) * 10)),
				int(math.Round(float64(ps.angles[1]) * 10)),
			})
		}
		if len(entries) == 0 {
			return
		}
		out.PositionTimeline.Snapshots = append(out.PositionTimeline.Snapshots, snapshot{
			T: round1(at),
			P: entries,
		})
	}

	ensure := func(num int) *playerState {
		ps, ok := players[num]
		if !ok {
			ps = &playerState{num: num, alive: true}
			players[num] = ps
		}
		return ps
	}

	for {
		ev, err := src.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			if strict && errors.Is(err, parser.ErrStrict) {
				return fmt.Errorf("strict-mode violation: %w", err)
			}
			// Source.Next normally converts mvd.ErrEndOfDemo to io.EOF, but
			// the in-stream svc_disconnect "EndOfDemo" path returns the raw
			// sentinel through ParseOne — treat it as a clean end too,
			// matching the upstream registry's tolerance pattern.
			if err == mvd.ErrEndOfDemo {
				break
			}
			return err
		}

		t := ev.EventTime()
		lastEventTime = t

		// Flush any buckets whose right edge has passed. Use the event time
		// as the "now" cursor — we emit at most one snapshot per bucket,
		// at the bucket's right edge, capturing whichever state was current
		// at that time.
		for t >= nextBucketEdge {
			flushBucket(nextBucketEdge - bucketDur/2)
			nextBucketEdge += bucketDur
		}

		switch e := ev.(type) {
		case *events.ServerDataEvent:
			if e.Data != nil {
				out.Map = mapNameFromMapFile(e.Data.MapFile)
				if out.Map == "" {
					out.Map = strings.ToLower(strings.TrimSpace(e.Data.LevelName))
				}
			}
		case *events.UserInfoEvent:
			if e.Player == nil || e.Player.Spectator {
				continue
			}
			ps := ensure(e.Player.Slot)
			ps.name = e.Player.Name
			ps.team = e.Player.Team
		case *events.PlayerPositionEvent:
			ps := ensure(e.PlayerNum)
			ps.origin = e.Origin
			ps.angles = e.Angles
			ps.hasPos = true
		case *events.StatUpdateEvent:
			ps := ensure(e.PlayerNum)
			switch e.StatIndex {
			case events.StatHealth:
				ps.health = e.Value
				ps.alive = e.Value > 0
			case events.StatArmor:
				ps.armor = e.Value
			case events.StatItems:
				ps.items = e.Value
			}
		case *events.DeathEvent:
			ps := ensure(e.PlayerNum)
			ps.alive = false
		case *events.SpawnEvent:
			ps := ensure(e.PlayerNum)
			ps.alive = true
		}
	}

	// Final bucket flush
	if lastEventTime > nextBucketEdge-bucketDur {
		flushBucket(lastEventTime)
	}

	// MapFile is populated from svc_modellist, which arrives after the
	// initial ServerDataEvent — re-read at end to pick up the BSP name.
	if sd := p.ServerData(); sd != nil && sd.MapFile != "" {
		if name := mapNameFromMapFile(sd.MapFile); name != "" {
			out.Map = name
		}
	}

	// Players list (sorted by num, name fallback if userinfo missed)
	nums := make([]int, 0, len(players))
	for n, ps := range players {
		if ps.name == "" {
			continue
		}
		nums = append(nums, n)
	}
	sort.Ints(nums)
	for _, n := range nums {
		ps := players[n]
		out.PositionTimeline.Players = append(out.PositionTimeline.Players, playerMeta{
			Num:  ps.num,
			Name: ps.name,
			Team: ps.team,
		})
	}

	// data_quality block — strict mode succeeds with zero warnings;
	// lenient mode summarises whatever the parser collected.
	warnings := p.DiagnosticWarnings()
	out.DataQuality = buildDataQuality(warnings, strict)
	out.PositionTimeline.QualityMetrics = map[string]interface{}{
		"snapshot_count":   len(out.PositionTimeline.Snapshots),
		"player_count":     len(out.PositionTimeline.Players),
		"duration_seconds": round1(lastEventTime),
		"snap_hz":          snapHz,
	}

	enc := json.NewEncoder(w)
	if pretty {
		enc.SetIndent("", "  ")
	}
	return enc.Encode(out)
}

func buildDataQuality(warnings []parser.Warning, strict bool) map[string]interface{} {
	categories := map[string]int{}
	first := []warningSummary{}
	limit := 25
	for _, w := range warnings {
		categories[w.Type]++
		if len(first) < limit {
			first = append(first, warningSummary{Type: w.Type, Time: w.Time, Message: w.Message})
		}
	}
	out := map[string]interface{}{
		"parser":      "mvd_analyzer",
		"strict":      strict,
		"warning_count": len(warnings),
		"categories":  categories,
		"warnings":    first,
	}
	if strict && len(warnings) == 0 {
		out["bytes_unknown"] = 0
	}
	return out
}

func mapNameFromMapFile(mf string) string {
	if mf == "" {
		return ""
	}
	base := filepath.Base(mf)
	base = strings.TrimSuffix(base, ".bsp")
	return strings.ToLower(base)
}

func roundCoord(v float32) float64 {
	return math.Round(float64(v)*10) / 10
}

func round1(v float64) float64 {
	return math.Round(v*10) / 10
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

