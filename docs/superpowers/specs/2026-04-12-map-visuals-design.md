# Map Visuals: View Cones, Item Spawns, Weapon/Powerup Indicators

**Date:** 2026-04-12
**Scope:** Dashboard 2D canvas + 3D Three.js map views
**Mockups:** `phase0/data/mockups/map-visuals-design.html`, `phase0/data/mockups/view-cones-3d-design.html`

## Summary

Add three visual layers to the 2D and 3D map views: player view direction cones, item spawn/pickup indicators, and player weapon/powerup status. All data already exists in the Rust parser output — this is a plumbing + rendering change.

## Design Decisions

### Color Palette

Items have fixed canonical colors. Team colors are shifted to avoid overlap.

| Element | Color | Hex | Shape |
|---------|-------|-----|-------|
| **Team 1** | warm red-pink | `#ff4466` | dot + cone |
| **Team 2** | royal blue | `#4477dd` | dot + cone |
| **Quad** | cyan | `#00ffff` | diamond |
| **Pent** | orange | `#ff8800` | pentagram |
| **Ring** | purple | `#cc66ff` | ring outline |
| **Red Armor** | red | `#cc3333` | triangle |
| **Yellow Armor** | yellow | `#ccaa33` | triangle |
| **Green Armor** | green | `#33bb33` | triangle |
| **RL spawn** | yellow | `#ddcc44` | rocket shape |
| **LG spawn** | white | `#ddddf8` | lightning bolt |
| **RL pip** (player has RL) | yellow | `#ddcc44` | small square below dot |
| **LG pip** (player has LG) | white | `#ddddf8` | small square below dot |

### 1. View Direction Cones

- **Style:** Short cone (30px length, 40° spread)
- **Color:** Team color at 13-15% opacity (semi-transparent)
- **2D:** Canvas triangle from player dot center, oriented by yaw angle
- **3D:** Three.js ConeGeometry attached to player sphere group, rotated by yaw
- **Only shown for alive players**

### 2. Item Spawn Indicators

Items appear at their map position when spawned, dim when picked up.

- **Bright** (opacity 0.6-0.8) = item is on the map (available)
- **Dim** (opacity 0.15-0.18) = item has been picked up (respawn timer running)
- Each item type has a unique shape (see palette table) — readable even without color
- **Layer toggles** in the controls bar: Powerups, Weapons, Armor (default all on)

**Data flow:** The glue server needs to forward `item_entity_events` from the Rust JSON so the dashboard knows when each item spawns/despawns. Events carry `time`, `position[x,y,z]`, `item_name`, `event_type` (Spawned/PickedUp).

### 3. Powerup Carrier Glow

When a player has Quad or Pent active:
- **2D:** Two concentric stroke rings around the player dot (inner at opacity 0.4, outer at 0.15)
- **3D:** RingGeometry on the ground plane below the player sphere + PointLight, both pulsing
- **Quad glow:** cyan (`#00ffff`)
- **Pent glow:** orange (`#ff8800`)
- Glow disappears when the powerup expires or the player dies

**Data source:** The per-snapshot flags bitmask already has bit 2 = Quad. Pent needs to be added as bit 3.

### 4. Player Weapon Pips

Small 3-4px colored squares rendered below the player dot:
- **Has RL:** yellow pip (`#ddcc44`)
- **Has LG:** white pip (`#ddddf8`)
- **Naked (no RL or LG):** no pips shown
- Players can have 0, 1, or 2 pips

**Data source:** Per-snapshot flags bitmask already has bit 0 = RL, bit 1 = LG.

## Data Pipeline Changes

### Rust (`src/output/json.rs`)

1. **Add Pent to flags bitmask:** bit 3 = `IT_INVULNERABILITY`
2. **Update flags_encoding** doc string to include pent
3. **Add item_entity_events to position_timeline JSON** — array of `{t, item, type, x, y, z}` for spawns and pickups of RL, LG, armor (ga/ya/ra), quad, pent, ring

### Glue server (`phase0/glue-server.js`)

1. **Pass through pitch/yaw** from snapshot array indices 8, 9 into position objects as `pitch` and `yaw` (divide by 10 to restore float)
2. **Pass through flags** into position objects (already has the data at index 7, just not extracted)
3. **Forward item_entity_events** from parsed JSON to dashboard response

### Dashboard (`phase0/dashboard.html`)

**2D canvas (Replay tab):**
1. Draw view cone before player dot (so dot renders on top)
2. Draw item icons at their positions, bright/dim based on spawn state
3. Draw powerup glow rings around carrier dots
4. Draw weapon pips below player dots
5. Add layer toggle checkboxes in controls

**3D view (Replay tab):**
1. Add ConeGeometry to player groups, rotated by yaw
2. Add item spawn meshes (Three.js equivalents of the 2D shapes)
3. Add RingGeometry + PointLight for powerup carrier glow, pulsing animation
4. Weapon pips less critical in 3D (name labels already visible), but can add as sprite icons

**Validator tab** has its own map view — apply same changes there.

### Interpolation

The existing `interpolateSnap` function interpolates positions. It needs to also:
- Interpolate yaw angle (shortest-path angular interpolation to avoid 359°→1° spinning)
- Pass through flags and pitch (no interpolation needed for discrete values)

## Item State Tracking (Dashboard-side)

The dashboard needs to track per-item availability state across the timeline:
- On `Spawned` event: mark item as available (bright)
- On `PickedUp` event: mark item as unavailable (dim)
- When scrubbing backward: rebuild state from events before current time

Simple approach: at each render frame, scan item events up to `currentTime` to determine each item's last known state. With ~500 events per match this is negligible cost.

## Out of Scope

- Health pack indicators (minor items, too many spawns, clutter risk)
- SNG/GL/NG/SSG spawn indicators (minor weapons, not tactically critical)
- Ammo pack spawns
- Item respawn timers (would need server config knowledge)
