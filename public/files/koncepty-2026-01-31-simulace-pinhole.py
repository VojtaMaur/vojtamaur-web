#!/usr/bin/env python3
# pinhole_camera_forward_v2.py
# Forward (light-to-camera) Monte Carlo pinhole + skutečná geometrie "krabičky"
# + preview render (ne matplotlib graf)

from __future__ import annotations
import math
import argparse
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict

import numpy as np
from PIL import Image

# ----------------------------
# Optional test sphere (toggle here)
# ----------------------------
ADD_SPHERE = True  # set True to add a white test sphere in front of camera

SPHERE_SEED_OFFSET = 424242
SPHERE_R_MIN, SPHERE_R_MAX = 0.14, 0.28
SPHERE_SEGMENTS = 24
SPHERE_RINGS = 12
SPHERE_MAX_TRIES = 64



# ----------------------------
# Utilities
# ----------------------------

def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v if n == 0 else (v / n)

def dot(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0]*b[0] + a[1]*b[1] + a[2]*b[2])

def cross(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.array([
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0]
    ], dtype=np.float64)

def clamp01(x: np.ndarray) -> np.ndarray:
    return np.clip(x, 0.0, 1.0)

def to_srgb(linear: np.ndarray) -> np.ndarray:
    # gamma 2.2
    return np.power(clamp01(linear), 1.0/2.2)

def luminance(rgb: np.ndarray) -> np.ndarray:
    return 0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]


# ----------------------------
# Geometry / Materials
# ----------------------------

@dataclass
class Material:
    albedo: np.ndarray          # RGB reflectance (0..1)
    emission: np.ndarray        # RGB emission
    is_emissive: bool = False

@dataclass
class Triangle:
    v0: np.ndarray
    v1: np.ndarray
    v2: np.ndarray
    mat_id: int
    n: np.ndarray = None
    area: float = 0.0

    def __post_init__(self):
        e1 = self.v1 - self.v0
        e2 = self.v2 - self.v0
        nn = cross(e1, e2)
        a = 0.5 * np.linalg.norm(nn)
        self.area = float(a)
        self.n = normalize(nn) if a > 0 else np.array([0.0, 1.0, 0.0], dtype=np.float64)

def ray_triangle_intersect(ro: np.ndarray, rd: np.ndarray, tri: Triangle, eps=1e-9) -> Optional[Tuple[float, float, float]]:
    # Möller–Trumbore
    v0, v1, v2 = tri.v0, tri.v1, tri.v2
    e1 = v1 - v0
    e2 = v2 - v0
    pvec = cross(rd, e2)
    det = dot(e1, pvec)
    if abs(det) < eps:
        return None
    inv_det = 1.0 / det
    tvec = ro - v0
    u = dot(tvec, pvec) * inv_det
    if u < 0.0 or u > 1.0:
        return None
    qvec = cross(tvec, e1)
    v = dot(rd, qvec) * inv_det
    if v < 0.0 or u + v > 1.0:
        return None
    t = dot(e2, qvec) * inv_det
    if t <= eps:
        return None
    return (t, u, v)

class Scene:
    def __init__(self, triangles: List[Triangle], materials: List[Material]):
        self.tris = triangles
        self.mats = materials

        weights = []
        for tri in self.tris:
            mat = self.mats[tri.mat_id]
            if mat.is_emissive and tri.area > 0:
                strength = float(np.mean(mat.emission))
                weights.append(tri.area * max(0.0, strength))
            else:
                weights.append(0.0)
        self.emitter_weights = np.array(weights, dtype=np.float64)
        self.emitter_total = float(self.emitter_weights.sum())

    def intersect(self, ro: np.ndarray, rd: np.ndarray) -> Optional[Tuple[float, int]]:
        best_t = float("inf")
        best_id = -1
        for i, tri in enumerate(self.tris):
            hit = ray_triangle_intersect(ro, rd, tri)
            if hit is None:
                continue
            t, _, _ = hit
            if t < best_t:
                best_t = t
                best_id = i
        if best_id < 0:
            return None
        return (best_t, best_id)

    def occluded(self, ro: np.ndarray, rd: np.ndarray, max_t: float) -> bool:
        for tri in self.tris:
            hit = ray_triangle_intersect(ro, rd, tri)
            if hit is None:
                continue
            t, _, _ = hit
            if t < max_t:
                return True
        return False

    def sample_emitter(self, rng: np.random.Generator) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self.emitter_total <= 0:
            raise RuntimeError("Scene has no emissive triangles.")
        r = rng.random() * self.emitter_total
        acc = 0.0
        idx = 0
        for i, w in enumerate(self.emitter_weights):
            acc += float(w)
            if acc >= r:
                idx = i
                break
        tri = self.tris[idx]
        mat = self.mats[tri.mat_id]

        # uniform point on triangle
        u = rng.random()
        v = rng.random()
        su = math.sqrt(u)
        b0 = 1.0 - su
        b1 = su * (1.0 - v)
        b2 = su * v
        p = b0*tri.v0 + b1*tri.v1 + b2*tri.v2

        n = tri.n.copy()
        emit = mat.emission.copy()
        return p, n, emit


# ----------------------------
# Camera (pinhole)
# ----------------------------

class Camera:
    def __init__(
        self,
        pos: np.ndarray,
        look_at: np.ndarray,
        up: np.ndarray,
        sensor_dist: float,
        sensor_w: float,
        sensor_h: float,
        res_w: int,
        res_h: int,
        aperture_radius: float,
        shape: str = "circle",
    ):
        self.pos = pos.astype(np.float64)
        self.forward = normalize((look_at - pos).astype(np.float64))
        r = cross(self.forward, up.astype(np.float64))
        self.right = normalize(r)
        self.up = normalize(cross(self.right, self.forward))

        # aperture plane: z=0 at cam.pos
        # sensor plane: z=-sensor_dist behind
        self.sensor_dist = float(sensor_dist)
        self.sensor_w = float(sensor_w)
        self.sensor_h = float(sensor_h)
        self.W = int(res_w)
        self.H = int(res_h)

        self.aperture_radius = float(aperture_radius)
        self.shape = shape.lower()

        self._poly_verts = None
        if self.shape != "circle":
            n_sides = {
                "triangle": 3,
                "square": 4,
                "pentagon": 5,
                "hexagon": 6,
                "octagon": 8,
            }.get(self.shape, None)
            if n_sides is None:
                raise ValueError(f"Unknown shape: {shape}")
            self._poly_verts = self._regular_polygon(n_sides, self.aperture_radius)

    def world_to_cam(self, p: np.ndarray) -> np.ndarray:
        v = p - self.pos
        return np.array([dot(v, self.right), dot(v, self.up), dot(v, self.forward)], dtype=np.float64)

    def dir_world_to_cam(self, d: np.ndarray) -> np.ndarray:
        return np.array([dot(d, self.right), dot(d, self.up), dot(d, self.forward)], dtype=np.float64)

    @staticmethod
    def _regular_polygon(n: int, r: float) -> np.ndarray:
        verts = []
        for i in range(n):
            a = 2.0*math.pi*(i / n)
            verts.append([r*math.cos(a), r*math.sin(a)])
        return np.array(verts, dtype=np.float64)

    def aperture_area(self) -> float:
        if self.shape == "circle":
            return math.pi * self.aperture_radius * self.aperture_radius
        v = self._poly_verts
        area = 0.0
        for i in range(len(v)):
            x1, y1 = v[i]
            x2, y2 = v[(i+1) % len(v)]
            area += x1*y2 - y1*x2
        return abs(area) * 0.5

    def _inside_aperture(self, x: float, y: float) -> bool:
        if self.shape == "circle":
            return (x*x + y*y) <= (self.aperture_radius*self.aperture_radius)
        v = self._poly_verts
        px, py = x, y
        sign = None
        for i in range(len(v)):
            x1, y1 = v[i]
            x2, y2 = v[(i+1) % len(v)]
            ex, ey = (x2-x1), (y2-y1)
            cx, cy = (px-x1), (py-y1)
            z = ex*cy - ey*cx
            s = z >= 0
            if sign is None:
                sign = s
            elif s != sign:
                return False
        return True

    def sample_aperture_point(self, rng: np.random.Generator) -> Tuple[np.ndarray, float]:
        # uniform on aperture shape, returns world point + pdf
        if self.shape == "circle":
            u = rng.random()
            v = rng.random()
            rr = self.aperture_radius * math.sqrt(u)
            th = 2.0*math.pi*v
            x = rr * math.cos(th)
            y = rr * math.sin(th)
        else:
            verts = self._poly_verts
            n = len(verts)
            i = int(rng.integers(0, n))
            a = np.array([0.0, 0.0], dtype=np.float64)
            b = verts[i]
            c = verts[(i+1) % n]
            u = rng.random()
            v = rng.random()
            su = math.sqrt(u)
            p2 = (1.0-su)*a + su*(1.0-v)*b + su*v*c
            x, y = float(p2[0]), float(p2[1])

        world = self.pos + self.right*x + self.up*y
        pdf = 1.0 / max(1e-12, self.aperture_area())
        return world, pdf

    def ray_to_sensor_pixel(self, ro_world: np.ndarray, rd_world: np.ndarray) -> Optional[Tuple[int, int]]:
        ro = self.world_to_cam(ro_world)
        rd = self.dir_world_to_cam(rd_world)

        dz = rd[2]
        if abs(dz) < 1e-12:
            return None

        t_ap = (0.0 - ro[2]) / dz
        if t_ap <= 1e-9:
            return None
        p_ap = ro + t_ap * rd
        if not self._inside_aperture(float(p_ap[0]), float(p_ap[1])):
            return None

        t_s = (-self.sensor_dist - ro[2]) / dz
        if t_s <= t_ap + 1e-9:
            return None
        p_s = ro + t_s * rd

        x, y = float(p_s[0]), float(p_s[1])
        if abs(x) > self.sensor_w * 0.5 or abs(y) > self.sensor_h * 0.5:
            return None

        u = (x / self.sensor_w) + 0.5
        v = (y / self.sensor_h) + 0.5
        ix = int(u * self.W)
        iy = int((1.0 - v) * self.H)
        if ix < 0 or ix >= self.W or iy < 0 or iy >= self.H:
            return None
        return (ix, iy)


# ----------------------------
# Sampling: diffuse bounce
# ----------------------------

def cosine_hemisphere(rng: np.random.Generator) -> np.ndarray:
    u1 = rng.random()
    u2 = rng.random()
    r = math.sqrt(u1)
    theta = 2.0*math.pi*u2
    x = r * math.cos(theta)
    y = r * math.sin(theta)
    z = math.sqrt(max(0.0, 1.0 - u1))
    return np.array([x, y, z], dtype=np.float64)

def tangent_frame(n: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    if abs(n[0]) > 0.1:
        a = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    else:
        a = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    t = normalize(cross(a, n))
    b = cross(n, t)
    return t, b

def to_world(local_dir: np.ndarray, n: np.ndarray) -> np.ndarray:
    t, b = tangent_frame(n)
    return normalize(local_dir[0]*t + local_dir[1]*b + local_dir[2]*n)


# ----------------------------
# Forward renderer (light -> scene -> camera)
# ----------------------------

class Renderer:
    def __init__(self, scene: Scene, cam: Camera, rng: np.random.Generator):
        self.scene = scene
        self.cam = cam
        self.rng = rng

    def render(self, paths: int, max_bounces: int, exposure: float, iso: int, bw: bool) -> np.ndarray:
        H, W = self.cam.H, self.cam.W
        accum = np.zeros((H, W, 3), dtype=np.float64)

        # DŮLEŽITÝ: aperture_area se už objeví přes 1/pdf (pdf=1/A => váha *A).
        # Když ji násobíš ještě jednou, zničíš jas o několik řádů.
        base_scale = float(exposure)

        report_every = max(1, paths // 100)
        for i in range(paths):
            if (i+1) % report_every == 0 or i == 0:
                pct = int((i+1) * 100 / paths)
                print(f"\rTracing paths: {pct:3d}% ({i+1}/{paths})", end="", flush=True)

            x, n, Le = self.scene.sample_emitter(self.rng)
            d = to_world(cosine_hemisphere(self.rng), n)

            throughput = Le.copy()
            ro = x + 1e-4 * n

            for bounce in range(max_bounces + 1):
                hit = self.scene.intersect(ro, d)
                # segment length
                max_t = hit[0] if hit is not None else float("inf")

                # connect to camera aperture (next-event estimation)
                ap_world, ap_pdf = self.cam.sample_aperture_point(self.rng)
                to_ap = ap_world - ro
                dist_ap = float(np.linalg.norm(to_ap))
                if dist_ap > 1e-9:
                    dir_ap = to_ap / dist_ap
                    # visibility
                    if not self.scene.occluded(ro, dir_ap, dist_ap - 1e-4):
                        pix = self.cam.ray_to_sensor_pixel(ro, dir_ap)
                        if pix is not None:
                            ix, iy = pix
                            dir_cam = self.cam.dir_world_to_cam(dir_ap)
                            cos_ap = max(0.0, -dir_cam[2])  # towards sensor (negative z)
                            contrib = throughput * (cos_ap / max(1e-9, dist_ap*dist_ap))
                            contrib *= (base_scale / max(1e-12, ap_pdf))
                            accum[iy, ix, :] += contrib

                if hit is None:
                    break

                t, tri_id = hit
                tri = self.scene.tris[tri_id]
                mat = self.scene.mats[tri.mat_id]

                hp = ro + t * d
                hn = tri.n
                if dot(hn, d) > 0:
                    hn = -hn

                if mat.is_emissive:
                    break

                throughput *= mat.albedo

                if bounce >= 1:
                    p = float(np.clip(np.mean(throughput), 0.05, 0.95))
                    if self.rng.random() > p:
                        break
                    throughput /= p

                d = to_world(cosine_hemisphere(self.rng), hn)
                ro = hp + 1e-4 * hn

        print("\nDone tracing.")

        gain = max(1e-6, iso / 100.0)
        img = accum * gain

        # jednoduchý read noise (roste s gainem)
        read_sigma = 0.0005 * math.sqrt(gain)
        img += self.rng.normal(0.0, read_sigma, size=img.shape)

        if bw:
            y = luminance(img)
            img = np.stack([y, y, y], axis=-1)

        return img


# ----------------------------
# Geometry helpers
# ----------------------------

def add_quad(tris: List[Triangle], v00, v10, v11, v01, mat_id: int):
    v00 = np.array(v00, dtype=np.float64)
    v10 = np.array(v10, dtype=np.float64)
    v11 = np.array(v11, dtype=np.float64)
    v01 = np.array(v01, dtype=np.float64)
    tris.append(Triangle(v00, v10, v11, mat_id))
    tris.append(Triangle(v00, v11, v01, mat_id))

def _in_view(cam: Camera, p_world: np.ndarray, margin: float = 0.0) -> bool:
    # Rough frustum test in camera space (pinhole). margin is a world-space slack (e.g. sphere radius).
    p = cam.world_to_cam(p_world)
    z = float(p[2])
    if z <= 1e-6:
        return False
    max_x = z * (cam.sensor_w * 0.5) / cam.sensor_dist
    max_y = z * (cam.sensor_h * 0.5) / cam.sensor_dist
    return (abs(float(p[0])) + margin) <= max_x and (abs(float(p[1])) + margin) <= max_y


def add_uv_sphere(tris: List[Triangle], center: np.ndarray, radius: float, mat_id: int,
                  rings: int = 12, segments: int = 24):
    c = center.astype(np.float64)
    r = float(radius)

    verts = []
    for i in range(rings + 1):
        phi = math.pi * (i / rings)
        y = math.cos(phi)
        rr = math.sin(phi)
        row = []
        for j in range(segments):
            th = 2.0 * math.pi * (j / segments)
            x = rr * math.cos(th)
            z = rr * math.sin(th)
            row.append(c + r * np.array([x, y, z], dtype=np.float64))
        verts.append(row)

    for i in range(rings):
        for j in range(segments):
            j2 = (j + 1) % segments
            v00 = verts[i][j]
            v01 = verts[i][j2]
            v10 = verts[i + 1][j]
            v11 = verts[i + 1][j2]

            if i == 0:
                tris.append(Triangle(v00, v10, v11, mat_id))
            elif i == rings - 1:
                tris.append(Triangle(v00, v10, v01, mat_id))
            else:
                tris.append(Triangle(v00, v10, v11, mat_id))
                tris.append(Triangle(v00, v11, v01, mat_id))


def add_random_sphere_in_view(tris: List[Triangle], mats: List[Material], cam: Camera, seed: int):
    # Add a white diffuse material for the test sphere
    mats.append(Material(np.array([0.92, 0.92, 0.92], dtype=np.float64), np.zeros(3), False))
    mat_sphere = len(mats) - 1

    rng = np.random.default_rng(int(seed) + int(SPHERE_SEED_OFFSET))

    for _ in range(int(SPHERE_MAX_TRIES)):
        rad = float(rng.uniform(SPHERE_R_MIN, SPHERE_R_MAX))

        z = float(rng.uniform(0.9, 2.2))
        x = float(rng.uniform(-0.55, 0.55))
        y = float(rng.uniform(-0.15, 0.75))

        # keep above floor y=-0.6
        y = max(y, -0.6 + rad + 0.02)

        center = np.array([x, y, z], dtype=np.float64)
        if _in_view(cam, center, margin=rad):
            add_uv_sphere(tris, center, rad, mat_sphere, rings=SPHERE_RINGS, segments=SPHERE_SEGMENTS)
            return

    # fallback: deterministic center if RNG keeps missing
    center = np.array([0.0, 0.15, 1.55], dtype=np.float64)
    rad = 0.22
    add_uv_sphere(tris, center, rad, mat_sphere, rings=SPHERE_RINGS, segments=SPHERE_SEGMENTS)



# ----------------------------
# Scene: low-poly triangle world + area light
# ----------------------------

def build_triangle_scene(seed: int = 0) -> Tuple[List[Triangle], List[Material]]:
    rng = np.random.default_rng(seed)

    mats: List[Material] = []
    def M(alb, emi=(0,0,0), e=False):
        mats.append(Material(np.array(alb, dtype=np.float64), np.array(emi, dtype=np.float64), e))
        return len(mats)-1

    MAT_FLOOR = M((0.70, 0.70, 0.70))
    MAT_WALL  = M((0.60, 0.62, 0.66))
    MAT_RED   = M((0.85, 0.20, 0.20))
    MAT_GREEN = M((0.20, 0.85, 0.20))
    MAT_BLUE  = M((0.20, 0.35, 0.90))
    MAT_YEL   = M((0.90, 0.85, 0.15))
    MAT_CAM   = M((0.05, 0.05, 0.05))
    MAT_LIGHT = M((0.0, 0.0, 0.0), emi=(35.0, 35.0, 35.0), e=True)

    tris: List[Triangle] = []

    # floor + back wall (aby to mělo kontext)
    add_quad(tris, (-2,-0.6,0.3), ( 2,-0.6,0.3), ( 2,-0.6,3.0), (-2,-0.6,3.0), MAT_FLOOR)
    add_quad(tris, (-2,-0.6,3.0), ( 2,-0.6,3.0), ( 2, 1.4,3.0), (-2, 1.4,3.0), MAT_WALL)

    # emissive quad nad scénou
    add_quad(tris, (-0.45, 1.15, 1.00), (0.45, 1.15, 1.00), (0.45, 1.15, 1.65), (-0.45, 1.15, 1.65), MAT_LIGHT)

    # pár "objektů" z random trojúhelníků
    palette = [MAT_RED, MAT_GREEN, MAT_BLUE, MAT_YEL]
    for k in range(26):
        cx = rng.uniform(-0.9, 0.9)
        cy = rng.uniform(-0.45, 0.65)
        cz = rng.uniform(0.65, 2.25)
        s  = rng.uniform(0.06, 0.22)

        v0 = np.array([cx, cy, cz]) + rng.normal(0, s, 3)
        v1 = np.array([cx, cy, cz]) + rng.normal(0, s, 3)
        v2 = np.array([cx, cy, cz]) + rng.normal(0, s, 3)

        mat_id = int(palette[k % len(palette)])
        tris.append(Triangle(v0, v1, v2, mat_id))

    return tris, mats


# ----------------------------
# Camera box geometry (krabička + clona s dírou)
# ----------------------------

def _regular_polygon_2d(n: int, r: float) -> np.ndarray:
    pts = []
    for i in range(n):
        a = 2.0*math.pi*(i / n)
        pts.append([r*math.cos(a), r*math.sin(a)])
    return np.array(pts, dtype=np.float64)

def add_camera_box(tris: List[Triangle], cam: Camera, mat_cam: int, box_w: float, box_h: float, depth: float):
    # cam coords -> world
    def cw(x, y, z):
        return cam.pos + cam.right*x + cam.up*y + cam.forward*z

    # 8 vertices: front rectangle at z=0, back at z=-depth
    hw = box_w * 0.5
    hh = box_h * 0.5
    zf = 0.0
    zb = -depth

    F = [
        cw(-hw, -hh, zf),
        cw( hw, -hh, zf),
        cw( hw,  hh, zf),
        cw(-hw,  hh, zf),
    ]
    B = [
        cw(-hw, -hh, zb),
        cw( hw, -hh, zb),
        cw( hw,  hh, zb),
        cw(-hw,  hh, zb),
    ]

    # sides (front is handled by diaphragm)
    # bottom
    add_quad(tris, F[0], F[1], B[1], B[0], mat_cam)
    # right
    add_quad(tris, F[1], F[2], B[2], B[1], mat_cam)
    # top
    add_quad(tris, F[2], F[3], B[3], B[2], mat_cam)
    # left
    add_quad(tris, F[3], F[0], B[0], B[3], mat_cam)
    # back
    add_quad(tris, B[1], B[0], B[3], B[2], mat_cam)

    # diaphragm ring at z=0: outer polygon -> inner aperture polygon
    if cam.shape == "circle":
        n = 32
    else:
        n = {"triangle":3, "square":4, "pentagon":5, "hexagon":6, "octagon":8}[cam.shape]

    outer_r = 0.45 * min(box_w, box_h)  # keep it inside front rect
    inner_r = cam.aperture_radius

    outer = _regular_polygon_2d(n, outer_r)
    inner = _regular_polygon_2d(n, inner_r)

    # Triangulate ring: quad per side -> 2 tris, CCW seen from +forward
    for i in range(n):
        j = (i+1) % n
        o0 = cw(outer[i,0], outer[i,1], 0.0)
        o1 = cw(outer[j,0], outer[j,1], 0.0)
        i0 = cw(inner[i,0], inner[i,1], 0.0)
        i1 = cw(inner[j,0], inner[j,1], 0.0)

        # triangles: o0 -> o1 -> i1 and o0 -> i1 -> i0
        tris.append(Triangle(o0, o1, i1, mat_cam))
        tris.append(Triangle(o0, i1, i0, mat_cam))


# ----------------------------
# Preview render (debug, not physics): raycast from a 3rd-person camera
# ----------------------------

def preview_render(scene: Scene, out_path: str, pos: np.ndarray, look_at: np.ndarray, up: np.ndarray,
                   W: int = 900, H: int = 600, fov_deg: float = 55.0):
    forward = normalize(look_at - pos)
    right = normalize(cross(forward, up))
    upv = normalize(cross(right, forward))

    fov = math.radians(fov_deg)
    aspect = W / H
    half_h = math.tan(fov * 0.5)
    half_w = aspect * half_h

    # simple fixed light for shading (just so it doesn't look like a CAD export)
    light_dir = normalize(np.array([0.5, 0.9, 0.3], dtype=np.float64))

    img = np.zeros((H, W, 3), dtype=np.float64)

    for y in range(H):
        v = (1.0 - 2.0 * ((y + 0.5) / H)) * half_h
        for x in range(W):
            u = (2.0 * ((x + 0.5) / W) - 1.0) * half_w
            rd = normalize(forward + u*right + v*upv)
            ro = pos

            hit = scene.intersect(ro, rd)
            if hit is None:
                # background
                img[y, x] = np.array([0.95, 0.96, 0.98], dtype=np.float64)
                continue

            t, tri_id = hit
            tri = scene.tris[tri_id]
            mat = scene.mats[tri.mat_id]
            n = tri.n
            if dot(n, rd) > 0:
                n = -n

            if mat.is_emissive:
                col = np.clip(mat.emission / 40.0, 0, 1)
            else:
                ndl = max(0.0, dot(n, light_dir))
                col = mat.albedo * (0.18 + 0.82*ndl)

            img[y, x] = col

    # gamma
    img_srgb = to_srgb(img)
    out8 = (clamp01(img_srgb) * 255.0 + 0.5).astype(np.uint8)
    Image.fromarray(out8, mode="RGB").save(out_path)
    print(f"Saved preview to: {out_path}")


# ----------------------------
# Main
# ----------------------------

def main():
    ap = argparse.ArgumentParser(description="Forward pinhole (light->camera) + real camera box + preview debug render.")
    ap.add_argument("--out", default="render.png")
    ap.add_argument("--preview", action="store_true", help="Generate preview render (debug) as preview.png")
    ap.add_argument("--preview-out", default="preview.png")
    ap.add_argument("--preview-w", type=int, default=1000)
    ap.add_argument("--preview-h", type=int, default=700)
    ap.add_argument("--preview-fov", type=float, default=55.0)
    ap.add_argument("--preview-mode", type=str, default="wide", choices=["wide", "close"])

    ap.add_argument("--paths", type=int, default=250_000)
    ap.add_argument("--bounces", type=int, default=1)

    ap.add_argument("--exposure", type=float, default=1.0)
    ap.add_argument("--iso", type=int, default=800)
    ap.add_argument("--bw", action="store_true")

    ap.add_argument("--sensor-dist", type=float, default=0.05)
    ap.add_argument("--sensor-w", type=float, default=0.036)
    ap.add_argument("--sensor-h", type=float, default=0.024)
    ap.add_argument("--res-w", type=int, default=320)
    ap.add_argument("--res-h", type=int, default=240)

    ap.add_argument("--aperture-radius", type=float, default=0.0015)
    ap.add_argument("--shape", type=str, default="circle", help="circle|triangle|square|pentagon|hexagon|octagon")

    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    # --- build triangle scene ---
    tris, mats = build_triangle_scene(seed=args.seed)

    # --- camera under test: at origin, looking +Z ---
    cam_pos = np.array([0.0, 0.0, 0.0], dtype=np.float64)
    cam = Camera(
        pos=cam_pos,
        look_at=np.array([0.0, 0.0, 1.0], dtype=np.float64),
        up=np.array([0.0, 1.0, 0.0], dtype=np.float64),
        sensor_dist=args.sensor_dist,
        sensor_w=args.sensor_w,
        sensor_h=args.sensor_h,
        res_w=args.res_w,
        res_h=args.res_h,
        aperture_radius=args.aperture_radius,
        shape=args.shape,
    )

    # --- optional test sphere (deterministic, kept in view) ---
    if ADD_SPHERE:
        add_random_sphere_in_view(tris, mats, cam, seed=args.seed)

    # --- add camera box geometry (krabička + clona) ---
    # Real sizes, žádný scaling. Jen to konečně existuje jako trojúhelníky.
    MAT_CAM = None
    # find camera material id: it's the last one inserted in build_triangle_scene, but let's map by albedo
    # (safe enough for this demo)
    for i, m in enumerate(mats):
        if np.allclose(m.albedo, np.array([0.05,0.05,0.05])) and not m.is_emissive:
            MAT_CAM = i
            break
    if MAT_CAM is None:
        mats.append(Material(np.array([0.05,0.05,0.05]), np.zeros(3), False))
        MAT_CAM = len(mats)-1

    add_camera_box(tris, cam, MAT_CAM, box_w=0.12, box_h=0.09, depth=max(0.10, args.sensor_dist*2.2))

    scene = Scene(tris, mats)

    # --- preview debug render (so you see the box + hole + scene) ---
    if args.preview:
        if args.preview_mode == "wide":
            ppos = np.array([0.55, 0.35, -0.55], dtype=np.float64)
            plook = np.array([0.0, 0.05, 1.15], dtype=np.float64)
        else:  # close
            ppos = np.array([0.18, 0.10, -0.22], dtype=np.float64)
            plook = np.array([0.0, 0.00, 0.35], dtype=np.float64)

        preview_render(
            scene,
            out_path=args.preview_out,
            pos=ppos,
            look_at=plook,
            up=np.array([0.0, 1.0, 0.0], dtype=np.float64),
            W=args.preview_w,
            H=args.preview_h,
            fov_deg=args.preview_fov
        )

    # --- physics render ---
    ren = Renderer(scene, cam, rng)
    img_lin = ren.render(
        paths=args.paths,
        max_bounces=args.bounces,
        exposure=args.exposure,
        iso=args.iso,
        bw=args.bw,
    )

    # tone map (Reinhard) + gamma
    img_tm = img_lin / (1.0 + np.maximum(img_lin, 0.0))
    img_srgb = to_srgb(img_tm)

    out8 = (clamp01(img_srgb) * 255.0 + 0.5).astype(np.uint8)
    Image.fromarray(out8, mode="RGB").save(args.out)
    print(f"Saved render to: {args.out}")


if __name__ == "__main__":
    main()
