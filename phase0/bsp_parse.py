#!/usr/bin/env python3
"""BSP v29 parser — extracts geometry lumps into flat binaries for CUDA consumption.

Usage:
    python bsp_parse.py <bsp_file> <output_dir>

Example:
    python bsp_parse.py data/dm3.bsp data
"""

import json
import sys
from pathlib import Path

import numpy as np
from construct import (
    Array,
    Bytes,
    Computed,
    Float32l,
    Int16sl,
    Int16ul,
    Int32sl,
    Struct,
    this,
)

# ── BSP v29 header ──────────────────────────────────────────────────────────

LUMP_COUNT = 15

LumpDescriptor = Struct(
    "offset" / Int32sl,
    "length" / Int32sl,
)

BspHeader = Struct(
    "version" / Int32sl,
    "lumps" / Array(LUMP_COUNT, LumpDescriptor),
)

# ── Lump struct definitions ─────────────────────────────────────────────────

# Lump indices (Quake 1 BSP v29 order)
LUMP_PLANES = 1
LUMP_VERTEXES = 3
LUMP_FACES = 7
LUMP_CLIPNODES = 9
LUMP_LEAVES = 10
LUMP_EDGES = 12
LUMP_SURFEDGES = 13
LUMP_MODELS = 14

Plane = Struct(
    "normal" / Array(3, Float32l),
    "dist" / Float32l,
    "type" / Int32sl,
)  # 20 bytes

Vertex = Struct(
    "point" / Array(3, Float32l),
)  # 12 bytes

Face = Struct(
    "planenum" / Int16sl,
    "side" / Int16sl,
    "firstedge" / Int32sl,
    "numedges" / Int16sl,
    "texinfo" / Int16sl,
    "styles" / Bytes(4),
    "lightofs" / Int32sl,
)  # 20 bytes

Clipnode = Struct(
    "planenum" / Int32sl,
    "children" / Array(2, Int16sl),
)  # 8 bytes

Leaf = Struct(
    "contents" / Int32sl,
    "visofs" / Int32sl,
    "mins" / Array(3, Int16sl),
    "maxs" / Array(3, Int16sl),
    "firstmarksurface" / Int16ul,
    "nummarksurfaces" / Int16ul,
    "ambient_level" / Bytes(4),
)  # 28 bytes

Edge = Struct(
    "v" / Array(2, Int16ul),
)  # 4 bytes

Surfedge = Struct(
    "value" / Int32sl,
)  # 4 bytes

Model = Struct(
    "mins" / Array(3, Float32l),
    "maxs" / Array(3, Float32l),
    "origin" / Array(3, Float32l),
    "headnode" / Array(4, Int32sl),
    "visleafs" / Int32sl,
    "firstface" / Int32sl,
    "numfaces" / Int32sl,
)  # 64 bytes

# ── Lump sizes ──────────────────────────────────────────────────────────────

LUMP_SIZES = {
    LUMP_PLANES: 20,
    LUMP_VERTEXES: 12,
    LUMP_FACES: 20,
    LUMP_CLIPNODES: 8,
    LUMP_LEAVES: 28,
    LUMP_EDGES: 4,
    LUMP_SURFEDGES: 4,
    LUMP_MODELS: 64,
}

LUMP_STRUCTS = {
    LUMP_PLANES: Plane,
    LUMP_VERTEXES: Vertex,
    LUMP_FACES: Face,
    LUMP_CLIPNODES: Clipnode,
    LUMP_LEAVES: Leaf,
    LUMP_EDGES: Edge,
    LUMP_SURFEDGES: Surfedge,
    LUMP_MODELS: Model,
}


def parse_lump(data: bytes, header, lump_idx):
    """Parse a single lump into a list of construct containers."""
    lump = header.lumps[lump_idx]
    struct = LUMP_STRUCTS[lump_idx]
    elem_size = LUMP_SIZES[lump_idx]
    count = lump.length // elem_size
    lump_data = data[lump.offset : lump.offset + lump.length]
    return Array(count, struct).parse(lump_data), count


def triangulate_faces(faces, surfedges, edges):
    """Fan-triangulate each face using surfedge walk.

    For each face:
      - Walk surfedges[firstedge .. firstedge+numedges] to get vertex indices
      - For surfedge >= 0: vertex = edges[surfedge].v[0]
      - For surfedge <  0: vertex = edges[-surfedge].v[1]
      - Fan from vertex 0: (v0, v1, v2), (v0, v2, v3), ...
    """
    triangles = []
    for face in faces:
        verts = []
        for i in range(face.numedges):
            se = surfedges[face.firstedge + i].value
            if se >= 0:
                verts.append(edges[se].v[0])
            else:
                verts.append(edges[-se].v[1])
        # Fan triangulation from first vertex
        for j in range(1, len(verts) - 1):
            triangles.append((verts[0], verts[j], verts[j + 1]))
    return triangles


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <bsp_file> <output_dir>", file=sys.stderr)
        sys.exit(1)

    bsp_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    data = bsp_path.read_bytes()
    print(f"Read {len(data):,} bytes from {bsp_path}")

    # ── Parse header ────────────────────────────────────────────────────────
    header = BspHeader.parse(data)
    if header.version != 29:
        print(f"ERROR: Expected BSP version 29, got {header.version}", file=sys.stderr)
        sys.exit(1)
    print(f"BSP version: {header.version}")

    # ── Parse lumps ─────────────────────────────────────────────────────────
    planes, n_planes = parse_lump(data, header, LUMP_PLANES)
    vertexes, n_vertexes = parse_lump(data, header, LUMP_VERTEXES)
    faces, n_faces = parse_lump(data, header, LUMP_FACES)
    clipnodes, n_clipnodes = parse_lump(data, header, LUMP_CLIPNODES)
    leaves, n_leaves = parse_lump(data, header, LUMP_LEAVES)
    edges, n_edges = parse_lump(data, header, LUMP_EDGES)
    surfedges, n_surfedges = parse_lump(data, header, LUMP_SURFEDGES)
    models, n_models = parse_lump(data, header, LUMP_MODELS)

    print(f"\nLump counts:")
    print(f"  Planes:     {n_planes:>6}")
    print(f"  Vertexes:   {n_vertexes:>6}")
    print(f"  Faces:      {n_faces:>6}")
    print(f"  Clipnodes:  {n_clipnodes:>6}")
    print(f"  Leaves:     {n_leaves:>6}")
    print(f"  Edges:      {n_edges:>6}")
    print(f"  Surfedges:  {n_surfedges:>6}")
    print(f"  Models:     {n_models:>6}")

    # ── Extract key model data ──────────────────────────────────────────────
    model0 = models[0]
    hull1_start = model0.headnode[1]
    world_mins = list(model0.mins)
    world_maxs = list(model0.maxs)

    print(f"\nHull 1 start node: {hull1_start}")
    print(f"World AABB: mins={world_mins}, maxs={world_maxs}")

    # ── Triangulate ─────────────────────────────────────────────────────────
    triangles = triangulate_faces(faces, surfedges, edges)
    n_triangles = len(triangles)
    print(f"Triangles:  {n_triangles:>6}")

    # ── Export flat binaries ────────────────────────────────────────────────

    # planes.bin — float32: [nx, ny, nz, dist, type_as_float] x N
    planes_arr = np.zeros((n_planes, 5), dtype=np.float32)
    for i, p in enumerate(planes):
        planes_arr[i, 0] = p.normal[0]
        planes_arr[i, 1] = p.normal[1]
        planes_arr[i, 2] = p.normal[2]
        planes_arr[i, 3] = p.dist
        planes_arr[i, 4] = float(p.type)
    (out_dir / "planes.bin").write_bytes(planes_arr.tobytes())
    print(f"\nWrote planes.bin        ({planes_arr.nbytes:>10,} bytes)")

    # clipnodes.bin — int32: [planenum, child0, child1, 0_pad] x N
    clip_arr = np.zeros((n_clipnodes, 4), dtype=np.int32)
    for i, c in enumerate(clipnodes):
        clip_arr[i, 0] = c.planenum
        clip_arr[i, 1] = c.children[0]
        clip_arr[i, 2] = c.children[1]
        # clip_arr[i, 3] = 0  (already zero)
    (out_dir / "clipnodes.bin").write_bytes(clip_arr.tobytes())
    print(f"Wrote clipnodes.bin     ({clip_arr.nbytes:>10,} bytes)")

    # vertexes.bin — float32: [x, y, z] x N
    vert_arr = np.zeros((n_vertexes, 3), dtype=np.float32)
    for i, v in enumerate(vertexes):
        vert_arr[i, 0] = v.point[0]
        vert_arr[i, 1] = v.point[1]
        vert_arr[i, 2] = v.point[2]
    (out_dir / "vertexes.bin").write_bytes(vert_arr.tobytes())
    print(f"Wrote vertexes.bin      ({vert_arr.nbytes:>10,} bytes)")

    # edges.bin — int32: [v0, v1] x N
    edge_arr = np.zeros((n_edges, 2), dtype=np.int32)
    for i, e in enumerate(edges):
        edge_arr[i, 0] = e.v[0]
        edge_arr[i, 1] = e.v[1]
    (out_dir / "edges.bin").write_bytes(edge_arr.tobytes())
    print(f"Wrote edges.bin         ({edge_arr.nbytes:>10,} bytes)")

    # surfedges.bin — int32: [surfedge] x N
    se_arr = np.zeros(n_surfedges, dtype=np.int32)
    for i, se in enumerate(surfedges):
        se_arr[i] = se.value
    (out_dir / "surfedges.bin").write_bytes(se_arr.tobytes())
    print(f"Wrote surfedges.bin     ({se_arr.nbytes:>10,} bytes)")

    # faces.bin — int32: [firstedge, numedges] x N
    face_arr = np.zeros((n_faces, 2), dtype=np.int32)
    for i, f in enumerate(faces):
        face_arr[i, 0] = f.firstedge
        face_arr[i, 1] = f.numedges
    (out_dir / "faces.bin").write_bytes(face_arr.tobytes())
    print(f"Wrote faces.bin         ({face_arr.nbytes:>10,} bytes)")

    # triangles.bin — int32: [v0, v1, v2] x N
    tri_arr = np.array(triangles, dtype=np.int32)
    (out_dir / "triangles.bin").write_bytes(tri_arr.tobytes())
    print(f"Wrote triangles.bin     ({tri_arr.nbytes:>10,} bytes)")

    # ── Export OBJ ──────────────────────────────────────────────────────────
    obj_path = out_dir / "dm3.obj"
    with open(obj_path, "w") as obj:
        obj.write("# BSP v29 exported geometry — dm3\n")
        for i in range(n_vertexes):
            obj.write(f"v {vert_arr[i,0]} {vert_arr[i,1]} {vert_arr[i,2]}\n")
        for t in triangles:
            # OBJ is 1-indexed
            obj.write(f"f {t[0]+1} {t[1]+1} {t[2]+1}\n")
    print(f"Wrote dm3.obj           ({obj_path.stat().st_size:>10,} bytes)")

    # ── Export metadata JSON ────────────────────────────────────────────────
    meta = {
        "hull1_start": int(hull1_start),
        "world_mins": [float(x) for x in world_mins],
        "world_maxs": [float(x) for x in world_maxs],
        "n_planes": n_planes,
        "n_clipnodes": n_clipnodes,
        "n_leaves": n_leaves,
        "n_faces": n_faces,
        "n_triangles": n_triangles,
        "n_vertexes": n_vertexes,
    }
    meta_path = out_dir / "bsp_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote bsp_meta.json     ({meta_path.stat().st_size:>10,} bytes)")

    print("\nDone.")


if __name__ == "__main__":
    main()
