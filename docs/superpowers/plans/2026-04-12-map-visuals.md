# Map Visuals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add view direction cones, item spawn/pickup indicators, weapon pips, and powerup glow to the 2D and 3D map views.

**Architecture:** Three-layer change: Rust emits Pent flag + item events → glue server passes through angles/flags/events → dashboard renders cones, items, pips, glows. All data already exists in the parser; this is plumbing + rendering.

**Tech Stack:** Rust (mimer binary), Node.js (glue-server.js), HTML5 Canvas + Three.js (dashboard.html)

**Spec:** `docs/superpowers/specs/2026-04-12-map-visuals-design.md`
**Mockups:** `phase0/data/mockups/map-visuals-design.html`, `phase0/data/mockups/view-cones-3d-design.html`

---

### Task 1: Add Pent flag + item events to Rust JSON output

**Files:**
- Modify: `src/output/json.rs:1148-1162` (flags bitmask)
- Modify: `src/output/json.rs:1205-1210` (flags_encoding doc)
- Modify: `src/output/json.rs:1165-1170` (position_timeline JSON object)
- Modify: `src/output/json.rs:730-757` (build_item_entities_json)

- [ ] **Step 1: Add IT_INVULNERABILITY to flags bitmask**

In `src/output/json.rs`, find the flags computation around line 1148:

```rust
let flags = ((p.items & IT_ROCKET_LAUNCHER != 0) as u8)
    | (((p.items & IT_LIGHTNING != 0) as u8) << 1)
    | (((p.items & IT_QUAD != 0) as u8) << 2);
```

Replace with:

```rust
let flags = ((p.items & IT_ROCKET_LAUNCHER != 0) as u8)
    | (((p.items & IT_LIGHTNING != 0) as u8) << 1)
    | (((p.items & IT_QUAD != 0) as u8) << 2)
    | (((p.items & IT_INVULNERABILITY != 0) as u8) << 3);
```

Also add the import at the top of the function. `IT_INVULNERABILITY` is defined in `src/mvd/types.rs` and should already be in scope via `use crate::mvd::types::*;` — verify.

Update the `flags_encoding` string in the JSON output from:

```rust
"flags_encoding": "bit0=rl, bit1=lg, bit2=quad",
```

to:

```rust
"flags_encoding": "bit0=rl, bit1=lg, bit2=quad, bit3=pent",
```

- [ ] **Step 2: Add item_events array to position_timeline JSON**

Add a new function in `src/output/json.rs` after `build_item_entities_json`:

```rust
fn build_item_events_for_timeline(state: &MatchState) -> Vec<serde_json::Value> {
    use crate::state::ItemEntityEventType;
    let dominated = ["rl", "lg", "quad", "pent", "ring", "armor"];
    state.item_entity_events.iter()
        .filter(|e| dominated.iter().any(|d| e.item_name.starts_with(d)))
        .map(|e| {
            serde_json::json!({
                "t": round1(e.time),
                "item": e.item_name,
                "type": match e.event_type {
                    ItemEntityEventType::Spawned => "spawn",
                    ItemEntityEventType::PickedUp => "pickup",
                },
                "x": e.position[0].round() as i32,
                "y": e.position[1].round() as i32,
                "z": e.position[2].round() as i32,
            })
        })
        .collect()
}
```

Then in `build_position_timeline_json`, add the `item_events` field to the returned JSON object, after the `"quality_metrics"` block:

```rust
"item_events": build_item_events_for_timeline(state),
```

- [ ] **Step 3: Build and verify output**

Run:
```bash
cargo build --release
cargo run --release -- data/testdemos/dm2_Milton_-s-_vs_Book_20251123_a5fe8c7c.mvd.gz --dump-analysis 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
pt = data['position_timeline']
# Check flags encoding
print('flags_encoding:', pt['flags_encoding'])
# Check a snapshot for pent bit
snap = pt['snapshots'][100]
for p in snap['p']:
    flags = p[7]
    print(f'  player {p[0]}: flags={flags:04b} rl={flags&1} lg={(flags>>1)&1} quad={(flags>>2)&1} pent={(flags>>3)&1}')
# Check item events
events = pt.get('item_events', [])
print(f'item_events: {len(events)} total')
for e in events[:5]:
    print(f'  t={e[\"t\"]} {e[\"type\"]:6s} {e[\"item\"]:10s} at ({e[\"x\"]},{e[\"y\"]},{e[\"z\"]})')
"
```

Expected: `flags_encoding` includes `bit3=pent`. `item_events` has ~200-500 entries with spawn/pickup types.

- [ ] **Step 4: Run tests**

```bash
cargo test
```

Expected: 125/125 pass. No test touches the flags bitmask or item events output format.

- [ ] **Step 5: Commit**

```bash
git add src/output/json.rs
git commit -m "feat: add pent flag (bit3) and item_events to position_timeline JSON"
```

---

### Task 2: Glue server — pass through angles, flags, and item events

**Files:**
- Modify: `phase0/glue-server.js:162-166` (position transform)
- Modify: `phase0/glue-server.js:191-199` (return object)
- Modify: `phase0/glue-server.js:249-252` (parse endpoint response)

- [ ] **Step 1: Add pitch, yaw, and flags to position objects**

In `phase0/glue-server.js`, find the position transform at line 162:

```js
positions[pinfo.name] = {
    x: entry[1], y: entry[2], z: entry[3],
    alive: !!entry[4],
    health: entry[5], armor: entry[6],
};
```

Replace with:

```js
positions[pinfo.name] = {
    x: entry[1], y: entry[2], z: entry[3],
    alive: !!entry[4],
    health: entry[5], armor: entry[6],
    flags: entry[7] || 0,
    pitch: (entry[8] || 0) / 10,
    yaw: (entry[9] || 0) / 10,
};
```

- [ ] **Step 2: Forward item_events in the demo object**

In the return object of `transformMimerJson` (line 191), add `itemEvents`:

```js
return {
    filename,
    map: mapName,
    duration,
    teams: Object.entries(teams).map(([name, players]) => ({ name, players })),
    players: playersMeta.map(p => ({ name: p.name, team: p.team, num: p.num })),
    snapshots,
    kills,
    itemEvents: pt.item_events || [],
};
```

- [ ] **Step 3: Verify glue server passes new fields**

Restart glue server and parse a demo via the dashboard or curl:

```bash
scp phase0/glue-server.js pinnaclepowerhouse:~/demopasha-dashboard/glue-server.js
ssh pinnaclepowerhouse "bash /tmp/restart-glue.sh"
```

Then on the dashboard, parse a demo and check browser console for `result.demo.snapshots[0].positions` — should now have `flags`, `pitch`, `yaw` fields. `result.demo.itemEvents` should be an array.

- [ ] **Step 4: Commit**

```bash
git add phase0/glue-server.js
git commit -m "feat: pass angles, flags, and item events through glue server"
```

---

### Task 3: Update team colors and add drawing helpers to dashboard

**Files:**
- Modify: `phase0/dashboard.html:718-722` (TEAM_COLORS)
- Modify: `phase0/dashboard.html:1124` (TEAM_COLORS_3D)
- Modify: `phase0/dashboard.html:1392` (VAL_TEAM_COLORS)
- Modify: `phase0/dashboard.html:1983` (VAL_TEAM_COLORS_3D)

- [ ] **Step 1: Update team color constants**

Replace the TEAM_COLORS array at line 718:

```js
const TEAM_COLORS = [
  {bg: 'rgba(230, 60, 60, 0.9)', trail: 'rgba(230, 60, 60, 0.25)', dead: 'rgba(230, 60, 60, 0.3)'},
  {bg: 'rgba(60, 130, 230, 0.9)', trail: 'rgba(60, 130, 230, 0.25)', dead: 'rgba(60, 130, 230, 0.3)'},
  {bg: 'rgba(60, 200, 80, 0.9)', trail: 'rgba(60, 200, 80, 0.25)', dead: 'rgba(60, 200, 80, 0.3)'},
  {bg: 'rgba(230, 180, 40, 0.9)', trail: 'rgba(230, 180, 40, 0.25)', dead: 'rgba(230, 180, 40, 0.3)'},
];
```

With the new palette (warm red-pink / royal blue):

```js
const TEAM_COLORS = [
  {bg: '#ff4466', trail: 'rgba(255, 68, 102, 0.25)', dead: 'rgba(255, 68, 102, 0.3)', cone: 'rgba(255, 68, 102, 0.13)', rgb: [255,68,102]},
  {bg: '#4477dd', trail: 'rgba(68, 119, 221, 0.25)', dead: 'rgba(68, 119, 221, 0.3)', cone: 'rgba(68, 119, 221, 0.13)', rgb: [68,119,221]},
  {bg: '#33bb55', trail: 'rgba(51, 187, 85, 0.25)', dead: 'rgba(51, 187, 85, 0.3)', cone: 'rgba(51, 187, 85, 0.13)', rgb: [51,187,85]},
  {bg: '#cc88dd', trail: 'rgba(204, 136, 221, 0.25)', dead: 'rgba(204, 136, 221, 0.3)', cone: 'rgba(204, 136, 221, 0.13)', rgb: [204,136,221]},
];
```

Update `TEAM_COLORS_3D` at line 1124:

```js
const TEAM_COLORS_3D = [0xff4466, 0x4477dd, 0x33bb55, 0xcc88dd];
```

Update `VAL_TEAM_COLORS` at line 1392 with the same pattern (add `cone` and `rgb` fields).

Update `VAL_TEAM_COLORS_3D` at line 1983:

```js
const VAL_TEAM_COLORS_3D = [0xff4466, 0x4477dd, 0x33bb55, 0xcc88dd];
```

- [ ] **Step 2: Add item/powerup color constants and shape drawing helpers**

Add after the TEAM_COLORS block (around line 724):

```js
// Item colors (fixed — canonical QW)
const ITEM_COLORS = {
  quad: '#00ffff', pent: '#ff8800', ring: '#cc66ff',
  ra: '#cc3333', ya: '#ccaa33', ga: '#33bb33',
  rl: '#ddcc44', lg: '#ddddf8',
};

// Map item_name from parser to our item type key
function itemKey(name) {
  if (name === 'quad') return 'quad';
  if (name === 'pent') return 'pent';
  if (name === 'ring') return 'ring';
  if (name === 'rl') return 'rl';
  if (name === 'lg') return 'lg';
  if (name.includes('armor')) {
    // armor names from parser: "armor" — we need to classify by entity,
    // but the parser just says "armor". We'll use a single armor color.
    return 'ya'; // default to yellow; refine later if parser distinguishes tiers
  }
  return null;
}

// 2D shape drawing functions
function drawItemShape(ctx, x, y, type, alpha) {
  ctx.globalAlpha = alpha;
  const c = ITEM_COLORS[type] || '#888';
  if (type === 'quad') {
    ctx.fillStyle = c;
    ctx.beginPath(); ctx.moveTo(x, y-7); ctx.lineTo(x+6, y); ctx.lineTo(x, y+7); ctx.lineTo(x-6, y); ctx.closePath(); ctx.fill();
  } else if (type === 'pent') {
    ctx.fillStyle = c;
    ctx.beginPath();
    for (let i = 0; i < 5; i++) { const a=(i*72-90)*Math.PI/180; const px=x+7*Math.cos(a),py=y+7*Math.sin(a); i===0?ctx.moveTo(px,py):ctx.lineTo(px,py); }
    ctx.closePath(); ctx.fill();
  } else if (type === 'ring') {
    ctx.strokeStyle = c; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI*2); ctx.stroke();
  } else if (type === 'ra' || type === 'ya' || type === 'ga') {
    ctx.fillStyle = c;
    ctx.beginPath(); ctx.moveTo(x, y-6); ctx.lineTo(x-5, y+4); ctx.lineTo(x+5, y+4); ctx.closePath(); ctx.fill();
  } else if (type === 'rl') {
    ctx.fillStyle = c;
    ctx.fillRect(x-4, y-2, 8, 4);
    ctx.beginPath(); ctx.moveTo(x+4, y-3); ctx.lineTo(x+7, y); ctx.lineTo(x+4, y+3); ctx.closePath(); ctx.fill();
  } else if (type === 'lg') {
    ctx.strokeStyle = c; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(x-2, y-5); ctx.lineTo(x+1, y-1); ctx.lineTo(x-1, y+1); ctx.lineTo(x+2, y+5); ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function drawViewCone(ctx, x, y, yawDeg, length, spreadDeg, color) {
  // Canvas Y is inverted vs QW; yaw 0 = east, 90 = north (canvas up)
  const rad = yawDeg * Math.PI / 180;
  const half = spreadDeg * Math.PI / 180 / 2;
  ctx.fillStyle = color;
  ctx.beginPath(); ctx.moveTo(x, y);
  ctx.lineTo(x + Math.cos(rad - half) * length, y - Math.sin(rad - half) * length);
  ctx.lineTo(x + Math.cos(rad + half) * length, y - Math.sin(rad + half) * length);
  ctx.closePath(); ctx.fill();
}

function drawPowerupGlow(ctx, x, y, type) {
  const c = type === 'quad' ? '#00ffff' : '#ff8800';
  ctx.strokeStyle = c; ctx.globalAlpha = 0.4; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI*2); ctx.stroke();
  ctx.globalAlpha = 0.15; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.arc(x, y, 13, 0, Math.PI*2); ctx.stroke();
  ctx.globalAlpha = 1;
}

function drawWeaponPips(ctx, x, y, flags) {
  let px = x - 4;
  const py = y + 8;
  if (flags & 1) { ctx.fillStyle = ITEM_COLORS.rl; ctx.fillRect(px, py, 3, 3); px += 5; }
  if (flags & 2) { ctx.fillStyle = ITEM_COLORS.lg; ctx.fillRect(px, py, 3, 3); }
}
```

- [ ] **Step 3: Commit**

```bash
git add phase0/dashboard.html
git commit -m "feat: update team colors and add item/cone drawing helpers"
```

---

### Task 4: Update interpolation to include angles and flags

**Files:**
- Modify: `phase0/dashboard.html:800-812` (Replay interpolateSnap)
- Modify: `phase0/dashboard.html:1760-1770` (Validator interpolateSnap)

- [ ] **Step 1: Update Replay tab interpolation**

Find the interpolation block at line 804:

```js
interpolated.positions[name] = {
    x: pa.x + (pb.x - pa.x) * frac,
    y: pa.y + (pb.y - pa.y) * frac,
    z: pa.z + (pb.z - pa.z) * frac,
    alive: frac < 0.5 ? pa.alive : pb.alive,
    health: Math.round(pa.health + (pb.health - pa.health) * frac),
    armor: Math.round(pa.armor + (pb.armor - pa.armor) * frac),
};
```

Replace with:

```js
// Shortest-path yaw interpolation (avoid 359→1 spinning)
let yawA = pa.yaw || 0, yawB = pb.yaw || 0;
let yawDiff = yawB - yawA;
if (yawDiff > 180) yawDiff -= 360;
if (yawDiff < -180) yawDiff += 360;

interpolated.positions[name] = {
    x: pa.x + (pb.x - pa.x) * frac,
    y: pa.y + (pb.y - pa.y) * frac,
    z: pa.z + (pb.z - pa.z) * frac,
    alive: frac < 0.5 ? pa.alive : pb.alive,
    health: Math.round(pa.health + (pb.health - pa.health) * frac),
    armor: Math.round(pa.armor + (pb.armor - pa.armor) * frac),
    flags: frac < 0.5 ? (pa.flags || 0) : (pb.flags || 0),
    pitch: (pa.pitch || 0) + ((pb.pitch || 0) - (pa.pitch || 0)) * frac,
    yaw: yawA + yawDiff * frac,
};
```

- [ ] **Step 2: Apply same change to Validator tab interpolation**

Find the Validator interpolation at line 1764 and apply the identical change (same code block, different variable names if any — verify they use `pa`/`pb` too).

- [ ] **Step 3: Commit**

```bash
git add phase0/dashboard.html
git commit -m "feat: interpolate yaw (shortest-path) and pass through flags"
```

---

### Task 5: Replay tab 2D — render cones, items, pips, glows

**Files:**
- Modify: `phase0/dashboard.html:830-913` (Replay 2D draw loop)
- Modify: `phase0/dashboard.html` (add layer toggle controls)

- [ ] **Step 1: Add item state tracking**

Add after the `drawWeaponPips` helper (from Task 3), before the draw loop function:

```js
// Compute item availability at a given time from itemEvents array
function getItemStates(itemEvents, time) {
  const states = {}; // key = "item_x_y_z", value = {item, x, y, z, available}
  if (!itemEvents) return states;
  for (const e of itemEvents) {
    if (e.t > time) break;
    const key = `${e.item}_${e.x}_${e.y}_${e.z}`;
    if (e.type === 'spawn') {
      states[key] = { item: e.item, x: e.x, y: e.y, z: e.z, available: true };
    } else if (e.type === 'pickup') {
      if (states[key]) states[key].available = false;
      else states[key] = { item: e.item, x: e.x, y: e.y, z: e.z, available: false };
    }
  }
  return states;
}
```

- [ ] **Step 2: Add layer toggle checkboxes**

Find the controls panel in the Replay tab HTML (near the `showDeadPlayers`, `showKillMarkers`, `showTrails`, `showNames` checkboxes). Add after the existing toggles:

```html
<label><input type="checkbox" id="showItemsPowerups" checked> Powerups</label>
<label><input type="checkbox" id="showItemsWeapons" checked> Weapons</label>
<label><input type="checkbox" id="showItemsArmor" checked> Armor</label>
```

- [ ] **Step 3: Update the 2D draw loop**

In the Replay tab's `drawFrame()` function (around line 830), after the trail drawing and kill markers, but **before** the "Draw player dots" block at line 882, add:

```js
// Draw item spawn indicators
const itemStates = getItemStates(currentDemo.itemEvents, currentTime);
const showPowerups = document.getElementById('showItemsPowerups')?.checked ?? true;
const showWeapons = document.getElementById('showItemsWeapons')?.checked ?? true;
const showArmor = document.getElementById('showItemsArmor')?.checked ?? true;

for (const st of Object.values(itemStates)) {
  const ik = itemKey(st.item);
  if (!ik) continue;
  const isPowerup = ik === 'quad' || ik === 'pent' || ik === 'ring';
  const isWeapon = ik === 'rl' || ik === 'lg';
  const isArmor = ik === 'ra' || ik === 'ya' || ik === 'ga';
  if (isPowerup && !showPowerups) continue;
  if (isWeapon && !showWeapons) continue;
  if (isArmor && !showArmor) continue;

  const [ix, iy] = worldToCanvas(st.x, st.y);
  drawItemShape(ctx, ix, iy, ik, st.available ? 0.7 : 0.15);
}
```

Then modify the existing player dot loop (line 882-913). Replace the block starting at "Draw player dots" with:

```js
// Draw player dots with cones, pips, and powerup glow
for (const player of currentDemo.players) {
    if (!enabledTeams.has(player.team) || !enabledPlayers.has(player.name)) continue;
    const pos = snap.positions[player.name];
    if (!pos) continue;
    if (pos.x === 0 && pos.y === 0 && pos.z === 0) continue;
    if (!pos.alive && !showDead) continue;

    const color = teamColorMap[player.team];
    const [cx, cy] = worldToCanvas(pos.x, pos.y);

    // Powerup glow (behind everything)
    if (pos.alive && pos.flags) {
      if (pos.flags & 4) drawPowerupGlow(ctx, cx, cy, 'quad');
      if (pos.flags & 8) drawPowerupGlow(ctx, cx, cy, 'pent');
    }

    // View cone (behind dot)
    if (pos.alive && pos.yaw !== undefined) {
      drawViewCone(ctx, cx, cy, pos.yaw, 30, 40, color.cone);
    }

    // Player dot
    const radius = pos.alive ? 5 : 3;
    ctx.fillStyle = pos.alive ? color.bg : color.dead;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();

    if (pos.alive) {
      ctx.strokeStyle = 'rgba(255,255,255,0.4)';
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // Weapon pips
    if (pos.alive && pos.flags) {
      drawWeaponPips(ctx, cx, cy, pos.flags);
    }

    if (showNames) {
      ctx.fillStyle = pos.alive ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,0.3)';
      ctx.font = '10px Consolas, Menlo, monospace';
      ctx.fillText(player.name, cx + 8, cy - 4);
      if (pos.alive) {
        ctx.fillStyle = 'rgba(255,255,255,0.4)';
        ctx.fillText(`${pos.health}/${pos.armor}`, cx + 8, cy + 7);
      }
    }
}
```

- [ ] **Step 4: Test in browser**

Push dashboard to pinnacle and reload. Parse a demo, play it back:
- Cones should point in the direction the player is looking
- Item icons should appear at spawn locations (bright when available, dim when picked up)
- Players with Quad should have cyan glow rings
- Players with RL/LG should show weapon pips below the dot
- Layer toggles should hide/show item categories

```bash
scp phase0/dashboard.html pinnaclepowerhouse:~/demopasha-dashboard/static/dashboard.html
```

- [ ] **Step 5: Commit**

```bash
git add phase0/dashboard.html
git commit -m "feat: 2D map — view cones, item spawns, weapon pips, powerup glow"
```

---

### Task 6: Replay tab 3D — render cones, items, powerup glow

**Files:**
- Modify: `phase0/dashboard.html:1245-1300` (updateThreePlayers)

- [ ] **Step 1: Update updateThreePlayers for cones and glows**

Find the `updateThreePlayers` function (around line 1245). Replace the player rendering block (lines 1258-1299) with code that adds:
- A `THREE.ConeGeometry` for the view cone, rotated by yaw
- `THREE.RingGeometry` + `THREE.PointLight` for Quad/Pent carrier glow
- Weapon info in the name label sprite

Replace the inner loop body (from `const teamIdx` to the `playerSpheres[player.name]` assignment):

```js
const teamIdx = currentDemo.teams.findIndex(t => t.name === player.team);
const color = TEAM_COLORS_3D[teamIdx % TEAM_COLORS_3D.length];

const group = new THREE.Group();
group.position.set(pos.x, pos.y, pos.z + 24);

// Player sphere
const radius = pos.alive ? 16 : 10;
const sphereGeo = new THREE.SphereGeometry(radius, 12, 8);
const sphereMat = new THREE.MeshPhongMaterial({
    color, emissive: color,
    emissiveIntensity: pos.alive ? 0.4 : 0.1,
    transparent: !pos.alive, opacity: pos.alive ? 1.0 : 0.4,
});
group.add(new THREE.Mesh(sphereGeo, sphereMat));

// View cone (alive only)
if (pos.alive && pos.yaw !== undefined) {
    const coneLen = 40;
    const halfAngle = 20 * Math.PI / 180;
    const coneRadius = coneLen * Math.tan(halfAngle);
    const coneGeo = new THREE.ConeGeometry(coneRadius, coneLen, 16, 1, true);
    coneGeo.rotateZ(-Math.PI / 2);
    coneGeo.translate(coneLen / 2, 0, 0);
    const coneMat = new THREE.MeshBasicMaterial({
        color, transparent: true, opacity: 0.15,
        side: THREE.DoubleSide, depthWrite: false,
    });
    const cone = new THREE.Mesh(coneGeo, coneMat);
    cone.rotation.z = pos.yaw * Math.PI / 180;
    group.add(cone);
}

// Powerup glow
const flags = pos.flags || 0;
if (pos.alive && (flags & 4 || flags & 8)) {
    const glowColor = (flags & 4) ? 0x00ffff : 0xff8800;
    const ringGeo = new THREE.RingGeometry(20, 25, 32);
    const ringMat = new THREE.MeshBasicMaterial({
        color: glowColor, transparent: true, opacity: 0.4,
        side: THREE.DoubleSide, depthWrite: false,
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = Math.PI / 2;
    ring.position.z = -22;
    group.add(ring);
    group.add(new THREE.PointLight(glowColor, 0.8, 80));
}

threeScene.add(group);

// Name label sprite
const canvas2 = document.createElement('canvas');
canvas2.width = 256; canvas2.height = 64;
const c2 = canvas2.getContext('2d');
c2.font = 'bold 28px Consolas, monospace';
c2.fillStyle = pos.alive ? '#ffffff' : '#666666';
c2.fillText(player.name, 4, 30);
c2.font = '20px Consolas, monospace';
c2.fillStyle = '#aaaaaa';
c2.fillText(`${pos.health}/${pos.armor}`, 4, 54);
const tex = new THREE.CanvasTexture(canvas2);
const spriteMat = new THREE.SpriteMaterial({ map: tex, transparent: true });
const sprite = new THREE.Sprite(spriteMat);
sprite.position.set(pos.x + 20, pos.y, pos.z + 56);
sprite.scale.set(120, 30, 1);
threeScene.add(sprite);

playerSpheres[player.name] = { mesh: group, label: sprite };
```

Note: The cleanup code at the top of `updateThreePlayers` removes old meshes via `threeScene.remove(playerSpheres[name].mesh)` — since we now use a Group, this still works (removing the group removes all children).

- [ ] **Step 2: Add 3D item spawn meshes**

Add item spawn rendering after the player loop in `updateThreePlayers`. Use the same `getItemStates` function from Task 5:

```js
// Remove old item meshes
if (window._threeItemMeshes) {
    for (const m of window._threeItemMeshes) threeScene.remove(m);
}
window._threeItemMeshes = [];

const itemStates = getItemStates(currentDemo.itemEvents, currentTime);
const showPowerups = document.getElementById('showItemsPowerups')?.checked ?? true;
const showWeapons = document.getElementById('showItemsWeapons')?.checked ?? true;
const showArmor = document.getElementById('showItemsArmor')?.checked ?? true;

for (const st of Object.values(itemStates)) {
    const ik = itemKey(st.item);
    if (!ik) continue;
    const isPowerup = ik === 'quad' || ik === 'pent' || ik === 'ring';
    const isWeapon = ik === 'rl' || ik === 'lg';
    const isArmor = ik === 'ra' || ik === 'ya' || ik === 'ga';
    if (isPowerup && !showPowerups) continue;
    if (isWeapon && !showWeapons) continue;
    if (isArmor && !showArmor) continue;

    const hex = parseInt((ITEM_COLORS[ik] || '#888888').replace('#', ''), 16);
    const opacity = st.available ? 0.7 : 0.15;

    let geo;
    if (ik === 'quad') geo = new THREE.OctahedronGeometry(10);
    else if (ik === 'pent') geo = new THREE.DodecahedronGeometry(10);
    else if (ik === 'ring') geo = new THREE.TorusGeometry(8, 2, 8, 16);
    else if (ik === 'ra' || ik === 'ya' || ik === 'ga') geo = new THREE.ConeGeometry(8, 12, 3);
    else geo = new THREE.BoxGeometry(8, 8, 8);

    const mat = new THREE.MeshStandardMaterial({
        color: hex, emissive: hex, emissiveIntensity: st.available ? 0.5 : 0.05,
        transparent: true, opacity,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(st.x, st.y, st.z + 10);
    threeScene.add(mesh);
    window._threeItemMeshes.push(mesh);
}
```

- [ ] **Step 3: Test in browser**

Reload dashboard, parse a demo, switch to 3D view. Orbit around and verify:
- Player spheres have view cones pointing in the correct direction
- Quad/Pent carriers have colored glow rings
- Item spawn meshes appear at correct positions, bright/dim based on availability

- [ ] **Step 4: Commit**

```bash
git add phase0/dashboard.html
git commit -m "feat: 3D map — view cones, item meshes, powerup glow"
```

---

### Task 7: Validator tab — apply same visuals

**Files:**
- Modify: `phase0/dashboard.html:1827-1868` (Validator 2D draw loop)
- Modify: `phase0/dashboard.html:2090-2130` (Validator 3D update)

- [ ] **Step 1: Update Validator 2D draw loop**

Apply the same pattern from Task 5 to the Validator tab's player rendering loop at line 1827. The Validator tab uses `valCtx`, `valWorldToCanvas`, `valDemo`, `valEnabledTeams`, `valEnabledPlayers`, and `valTeamColors`. Add:
- Item state rendering (using `valDemo.itemEvents`)
- View cones before player dots
- Powerup glow rings
- Weapon pips below dots

The drawing helpers (`drawViewCone`, `drawItemShape`, `drawPowerupGlow`, `drawWeaponPips`, `getItemStates`, `itemKey`) are global functions — they work with any canvas context passed as `ctx`. Pass `valCtx` instead of `ctx`.

- [ ] **Step 2: Update Validator 3D**

Apply the same 3D changes from Task 6 to the Validator tab's `updateValThreePlayers` function at line 2090. Use `valThreeScene` instead of `threeScene`.

- [ ] **Step 3: Test both views in Validator tab**

Parse a demo in the Validator tab, verify cones/items/glow appear in both 2D and 3D. Check that POV highlight ring still works correctly with the new rendering order.

- [ ] **Step 4: Commit**

```bash
git add phase0/dashboard.html
git commit -m "feat: Validator tab — cones, items, pips, glow (2D + 3D)"
```

---

### Task 8: Push to pinnacle, verify end-to-end, Codex review

**Files:**
- Deploy: `target/release/mimer` → pinnacle
- Deploy: `phase0/dashboard.html` → pinnacle
- Deploy: `phase0/glue-server.js` → pinnacle

- [ ] **Step 1: Build final binary and push all files**

```bash
cargo build --release
scp target/release/mimer pinnaclepowerhouse:~/demoparser/target/release/mimer
scp phase0/dashboard.html pinnaclepowerhouse:~/demopasha-dashboard/static/dashboard.html
scp phase0/glue-server.js pinnaclepowerhouse:~/demopasha-dashboard/glue-server.js
ssh pinnaclepowerhouse "bash /tmp/restart-glue.sh"
```

- [ ] **Step 2: End-to-end test on live dashboard**

Open `https://demopasha.xerious.org`, parse a demo from each map category (dm2, dm3, e1m2, schloss, phantombase). For each:
- Verify view cones render and track player direction
- Verify item spawns appear and dim on pickup
- Verify powerup glow on carriers
- Verify weapon pips under armed players
- Verify layer toggles work
- Check 3D view for all of the above
- Check Validator tab for all of the above

- [ ] **Step 3: Codex review**

Send all changed files to Codex for independent review before declaring complete:
- `src/output/json.rs` — Pent flag + item_events
- `phase0/glue-server.js` — angle/flag/event passthrough
- `phase0/dashboard.html` — colors, helpers, interpolation, 2D rendering, 3D rendering

- [ ] **Step 4: Address Codex findings and final commit**

Fix any issues found by Codex review. Push fixes to pinnacle.
