"""Bake Thorlabs-class mount skins as drop-in glbs.

Optic housings stay separate: lenses are non-uniformly scaled, mounts are not.
Artist files may overwrite these as long as the AABB stays the same.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from frontend_pyside.features.teaching_v2.assets import ASSET_DIR, MOUNT_MESH_SPECS, NATIVE_AABB_TOL_MM

MAT_ANO = (0.12, 0.14, 0.17, 1.0)
MAT_STEEL = (0.72, 0.75, 0.78, 1.0)


class Soup:
    def __init__(self) -> None:
        self.prims: dict[int, list[tuple[tuple[float, float, float], tuple[float, float, float]]]] = {0: [], 1: []}

    def tri(self, a, b, c, mat: int = 0) -> None:
        ax, ay, az = a
        bx, by, bz = b
        cx, cy, cz = c
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        normal = (nx / length, ny / length, nz / length)
        self.prims[mat].extend(((a, normal), (b, normal), (c, normal)))

    def quad(self, a, b, c, d, mat: int = 0) -> None:
        self.tri(a, b, c, mat)
        self.tri(a, c, d, mat)

    def box(self, x0, x1, y0, y1, z0, z1, mat: int = 0) -> None:
        p000, p100 = (x0, y0, z0), (x1, y0, z0)
        p110, p010 = (x1, y1, z0), (x0, y1, z0)
        p001, p101 = (x0, y0, z1), (x1, y0, z1)
        p111, p011 = (x1, y1, z1), (x0, y1, z1)
        self.quad(p000, p100, p110, p010, mat)
        self.quad(p001, p011, p111, p101, mat)
        self.quad(p000, p001, p101, p100, mat)
        self.quad(p010, p110, p111, p011, mat)
        self.quad(p000, p010, p011, p001, mat)
        self.quad(p100, p101, p111, p110, mat)

    def tube_x(self, x0, x1, r_in, r_out, n: int = 36, mat: int = 0) -> None:
        for i in range(n):
            a0 = 2 * math.pi * i / n
            a1 = 2 * math.pi * (i + 1) / n
            c0, s0 = math.cos(a0), math.sin(a0)
            c1, s1 = math.cos(a1), math.sin(a1)
            o00, o01 = (x0, r_out * c0, r_out * s0), (x0, r_out * c1, r_out * s1)
            o10, o11 = (x1, r_out * c0, r_out * s0), (x1, r_out * c1, r_out * s1)
            i00, i01 = (x0, r_in * c0, r_in * s0), (x0, r_in * c1, r_in * s1)
            i10, i11 = (x1, r_in * c0, r_in * s0), (x1, r_in * c1, r_in * s1)
            self.quad(o00, o10, o11, o01, mat)
            self.quad(i00, i01, i11, i10, mat)
            self.quad(o00, o01, i01, i00, mat)
            self.quad(o10, i10, i11, o11, mat)

    def tube_z(self, z0, z1, r_in, r_out, n: int = 28, mat: int = 0) -> None:
        for i in range(n):
            a0 = 2 * math.pi * i / n
            a1 = 2 * math.pi * (i + 1) / n
            c0, s0 = math.cos(a0), math.sin(a0)
            c1, s1 = math.cos(a1), math.sin(a1)
            o00, o01 = (r_out * c0, r_out * s0, z0), (r_out * c1, r_out * s1, z0)
            o10, o11 = (r_out * c0, r_out * s0, z1), (r_out * c1, r_out * s1, z1)
            i00, i01 = (r_in * c0, r_in * s0, z0), (r_in * c1, r_in * s1, z0)
            i10, i11 = (r_in * c0, r_in * s0, z1), (r_in * c1, r_in * s1, z1)
            self.quad(o00, o01, o11, o10, mat)
            self.quad(i00, i10, i11, i01, mat)
            self.quad(o00, o10, i10, i00, mat)
            self.quad(o01, i01, i11, o11, mat)

    def cyl_x(self, x0, x1, y, z, r, n: int = 16, mat: int = 1) -> None:
        for i in range(n):
            a0 = 2 * math.pi * i / n
            a1 = 2 * math.pi * (i + 1) / n
            p00 = (x0, y + r * math.cos(a0), z + r * math.sin(a0))
            p01 = (x0, y + r * math.cos(a1), z + r * math.sin(a1))
            p10 = (x1, y + r * math.cos(a0), z + r * math.sin(a0))
            p11 = (x1, y + r * math.cos(a1), z + r * math.sin(a1))
            self.quad(p00, p10, p11, p01, mat)
            self.tri((x0, y, z), p00, p01, mat)
            self.tri((x1, y, z), p11, p10, mat)


def _pad4(blob: bytes) -> bytes:
    return blob + b"\x00" * ((4 - len(blob) % 4) % 4)


def _write_glb(path: Path, soup: Soup, name: str) -> None:
    bin_blob = b""
    views: list[dict] = []
    accessors: list[dict] = []
    primitives: list[dict] = []
    materials = [
        {
            "name": "anodized",
            "pbrMetallicRoughness": {
                "baseColorFactor": list(MAT_ANO),
                "metallicFactor": 0.42,
                "roughnessFactor": 0.48,
            },
            "doubleSided": True,
        },
        {
            "name": "steel",
            "pbrMetallicRoughness": {
                "baseColorFactor": list(MAT_STEEL),
                "metallicFactor": 0.78,
                "roughnessFactor": 0.28,
            },
            "doubleSided": True,
        },
    ]
    for mat, corners in soup.prims.items():
        if not corners:
            continue
        positions = [p for p, _n in corners]
        normals = [n for _p, n in corners]
        mins = [min(v[i] for v in positions) for i in range(3)]
        maxs = [max(v[i] for v in positions) for i in range(3)]
        pos_bytes = b"".join(struct.pack("<3f", *p) for p in positions)
        nrm_bytes = b"".join(struct.pack("<3f", *n) for n in normals)
        idx_bytes = b"".join(struct.pack("<H", i) for i in range(len(positions)))
        chunks = ((pos_bytes, len(positions), 5126, "VEC3", {"min": mins, "max": maxs}), (nrm_bytes, len(normals), 5126, "VEC3", {}), (idx_bytes, len(positions), 5123, "SCALAR", {}))
        base = len(accessors)
        for blob, count, ctype, typ, extra in chunks:
            views.append({"buffer": 0, "byteOffset": len(bin_blob), "byteLength": len(blob)})
            accessors.append({"bufferView": len(views) - 1, "componentType": ctype, "count": count, "type": typ, **extra})
            bin_blob += _pad4(blob)
        primitives.append({"attributes": {"POSITION": base, "NORMAL": base + 1}, "indices": base + 2, "material": mat})
    payload = {
        "asset": {"version": "2.0", "generator": "optical_ml bake_mounts"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": name, "mesh": 0}],
        "meshes": [{"primitives": primitives}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(bin_blob)}],
        "materials": materials,
    }
    json_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_blob)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(json_bytes), b"JSON")
        + json_bytes
        + struct.pack("<I4s", len(bin_blob), b"BIN\x00")
        + bin_blob
    )


def _build_post_base() -> Soup:
    soup = Soup()
    soup.box(-12.5, 12.5, -12.5, 12.5, 0.0, 6.0)
    soup.tube_z(6.0, 10.0, 6.45, 9.0, n=28)
    soup.cyl_x(8.2, 12.5, 0.0, 8.0, 1.2, n=12)
    return soup


def _build_ring() -> Soup:
    soup = Soup()
    soup.tube_x(-5.0, 5.0, 6.55, 10.0, n=36)
    soup.tube_x(3.6, 5.0, 6.05, 6.55, n=36)
    soup.box(-3.0, 3.0, -2.2, 2.2, -10.0, -8.4)
    return soup


def _build_clamp() -> Soup:
    soup = Soup()
    soup.box(-28.0, -12.0, -9.0, 9.0, -13.0, -9.2)
    soup.box(-28.0, -12.0, -9.0, -5.4, -9.2, -5.5)
    soup.box(-28.0, -12.0, 5.4, 9.0, -9.2, -5.5)
    soup.cyl_x(-21.2, -18.8, 7.6, -7.4, 1.2, n=12)
    return soup


def _build_km() -> Soup:
    soup = Soup()
    soup.box(-14.0, -6.0, -13.0, 13.0, -13.0, 13.0)
    soup.cyl_x(-14.0, -6.0, 8.0, 8.0, 1.5, n=12)
    soup.cyl_x(-14.0, -6.0, -8.0, 8.0, 1.5, n=12)
    return soup


def _build_plate() -> Soup:
    soup = Soup()
    soup.box(0.0, 22.0, -17.0, 17.0, -21.0, -15.0)
    return soup


BUILDERS = {
    "mount_post_base": _build_post_base,
    "mount_ring": _build_ring,
    "mount_clamp": _build_clamp,
    "mount_km": _build_km,
    "mount_plate": _build_plate,
}


def bake(asset_dir: Path | None = None) -> list[str]:
    out = Path(asset_dir or ASSET_DIR)
    notes: list[str] = []
    for key, builder in BUILDERS.items():
        spec = MOUNT_MESH_SPECS[key]
        soup = builder()
        path = out / f"{key}.glb"
        _write_glb(path, soup, key)
        pts = [p for corners in soup.prims.values() for p, _n in corners]
        actual_min = tuple(min(p[i] for p in pts) for i in range(3))
        actual_max = tuple(max(p[i] for p in pts) for i in range(3))
        for axis, got, want in zip("xyz", actual_min, spec.min_xyz):
            if abs(got - want) > NATIVE_AABB_TOL_MM:
                notes.append(f"{key} min_{axis}={got:g} spec={want:g}")
        for axis, got, want in zip("xyz", actual_max, spec.max_xyz):
            if abs(got - want) > NATIVE_AABB_TOL_MM:
                notes.append(f"{key} max_{axis}={got:g} spec={want:g}")
    return notes


if __name__ == "__main__":
    failed = bake()
    if failed:
        raise SystemExit("\n".join(failed))
    print("baked", ", ".join(BUILDERS))
