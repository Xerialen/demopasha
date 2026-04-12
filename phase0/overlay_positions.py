#!/usr/bin/env python3
"""Overlay real player positions on the dm3 top-down render.

If positions are correct, you'll see clear trails along corridors and
clusters in rooms. If they're wrong, you'll see random scatter.
"""

import json
import struct
from pathlib import Path
from PIL import Image, ImageDraw

data = Path(__file__).parent / "data"

img = Image.open(data / "dm3_topdown.png").convert("RGBA")
width, height = img.size

meta = json.loads((data / "bsp_meta.json").read_text())
mins = meta["world_mins"]
maxs = meta["world_maxs"]

positions = []
raw = (data / "demo_positions.bin").read_bytes()
n_pos = len(raw) // 12
for i in range(n_pos):
    x, y, z = struct.unpack_from("<fff", raw, i * 12)
    if x == 0.0 and y == 0.0 and z == 0.0:
        continue
    positions.append((x, y, z))

print(f"Loaded {n_pos} positions, {len(positions)} after filtering (0,0,0) spectators")

range_x = maxs[0] - mins[0]
range_y = maxs[1] - mins[1]
scale = min((width - 20) / range_x, (height - 20) / range_y)

overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
draw = ImageDraw.Draw(overlay)

for x, y, z in positions:
    px = int(10 + (x - mins[0]) * scale)
    py = int(10 + (y - mins[1]) * scale)
    if 0 <= px < width and 0 <= py < height:
        draw.ellipse([px - 1, py - 1, px + 1, py + 1], fill=(255, 50, 50, 120))

result = Image.alpha_composite(img, overlay)
out_path = data / "dm3_positions_overlay.png"
result.save(out_path)
print(f"Saved: {out_path}")
print(f"  Plotted {len(positions)} positions as red dots on the dm3 top-down render")
print(f"  If correct: you should see trails in corridors and clusters in rooms")
