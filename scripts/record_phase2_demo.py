"""Record a 30-second schematic Phase 2 demo using matplotlib 3D rendering.

Renders the Track2SimPublisher simulation at 10 Hz with a proper 3D perspective
aerial view showing real asset geometry (drone bodies, convoy vehicles, server racks,
comms links, threat markers) — no flat 2D projection.

Primary real-scene capture now lives in scripts/record_cesium_demo.py.

Run this fallback on remote H100:
  cd /opt/hades && python3 scripts/record_phase2_demo.py
  # Optional: --duration-s 30 --out-dir /opt/hades/recordings --fps 10
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection

# Repo root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge.sim_publisher import Track2SimPublisher
try:
    from scripts.check_bridge import summarize_frame  # noqa: E402
except ImportError:
    def summarize_frame(frame: dict[str, Any]) -> str:
        convoy = frame.get("convoy", [])
        route = convoy[0].get("active_route_id", "main") if convoy else "main"
        compute_events = frame.get("compute_events", [])
        dropped = sum(1 for event in compute_events if event.get("dropped"))
        scheduled = len(compute_events) - dropped
        return (
            f"t={float(frame.get('t', 0.0)):06.3f} "
            f"drones={len(frame.get('drones', []))} "
            f"edges={len(frame.get('edges', []))} "
            f"convoy={len(convoy)} links={len(frame.get('links', []))} "
            f"threats={len(frame.get('threats', []))} route={route} "
            f"compute_events={len(compute_events)} scheduled={scheduled} dropped={dropped}"
        )


# ---------------------------------------------------------------------------
# Asset geometry helpers — minimal 3D shapes for each actor type
# ---------------------------------------------------------------------------

def _drone_body_quads(
    cx: float,
    cy: float,
    cz: float,
    size: float = 2.0,
    rotor_angles: tuple[float, ...] = (45, 135, 225, 315),
):
    """Return body and arm quads for a multirotor drone silhouette."""
    h = size * 0.25
    body = np.array([
        [cx - size, cy - size, cz],
        [cx + size, cy - size, cz],
        [cx + size, cy + size, cz],
        [cx - size, cy + size, cz],
    ])
    top = body.copy(); top[:, 2] += h
    sides = []
    for i in range(4):
        j = (i + 1) % 4
        sides.append(np.array([body[i], body[j], top[j], top[i]]))
    arms = []
    for angle in rotor_angles:
        rad = math.radians(angle)
        arm_end = np.array([cx + size * 1.4 * math.cos(rad), cy + size * 1.4 * math.sin(rad), cz + h / 2])
        arm_pts = np.array([
            [cx - 0.2 * math.cos(rad + math.pi / 2), cy - 0.2 * math.sin(rad + math.pi / 2), cz + h / 2],
            [cx + 0.2 * math.cos(rad + math.pi / 2), cy + 0.2 * math.sin(rad + math.pi / 2), cz + h / 2],
            arm_end + np.array([0.2 * math.cos(rad + math.pi / 2), 0.2 * math.sin(rad + math.pi / 2), 0]),
            arm_end + np.array([-0.2 * math.cos(rad + math.pi / 2), -0.2 * math.sin(rad + math.pi / 2), 0]),
        ])
        arms.append(arm_pts)
    return [body] + [top] + sides + arms


def _box_quads(cx: float, cy: float, cz: float, w: float, d: float, h: float):
    """Six faces of an axis-aligned box as vertex arrays."""
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - d / 2, cy + d / 2
    z0, z1 = cz, cz + h
    faces = [
        [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0]],  # bottom
        [[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]],  # top
        [[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]],  # front
        [[x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]],  # back
        [[x0, y0, z0], [x0, y1, z0], [x0, y1, z1], [x0, y0, z1]],  # left
        [[x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]],  # right
    ]
    return [np.array(f) for f in faces]


# ---------------------------------------------------------------------------
# Frame renderer
# ---------------------------------------------------------------------------

_PARENT_COLOR = "#FFC254"
_SMALL_COLOR  = "#78FF96"
_CONVOY_COLOR = "#E8E8E8"
_EDGE_COLOR   = "#4AB4FF"
_THREAT_COLOR = "#FF4646"
_LINK_WIFI    = "#5ACDFF"
_LINK_LORA    = "#78FFA0"
_ROUTE_ACTIVE = "#FFE880"
_ROUTE_DIM    = "#FFFFFF"
_BG_COLOR     = "#111518"
_TERRAIN_COLOR= "#1E2820"


def _route_pts(waypoints: list[tuple[float, float]], z: float = 0.5, steps: int = 80):
    pts = []
    for i in range(len(waypoints) - 1):
        x0, y0 = waypoints[i]
        x1, y1 = waypoints[i + 1]
        for k in range(steps):
            t = k / steps
            pts.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, z))
    pts.append((*waypoints[-1], z))
    return np.array(pts)


def render_frame(frame: dict[str, Any], out_path: Path, route_waypoints: dict, size=(1920, 1080), dpi=100) -> None:
    fig = plt.figure(figsize=(size[0] / dpi, size[1] / dpi), dpi=dpi, facecolor=_BG_COLOR)
    ax: Axes3D = fig.add_subplot(111, projection="3d", facecolor=_BG_COLOR)

    # Camera: aerial 3/4 view, tilted for depth
    ax.view_init(elev=38, azim=-60)
    ax.set_xlim(-620, 620)
    ax.set_ylim(-320, 320)
    ax.set_zlim(0, 80)
    ax.set_box_aspect([1240, 640, 160])
    for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
        pane.fill = False
        pane.set_edgecolor("#333333")
    ax.tick_params(colors="#555555", labelsize=0)
    ax.grid(True, color="#222228", linewidth=0.5, alpha=0.6)

    convoy_list = frame.get("convoy", [])
    active_route = convoy_list[0].get("active_route_id", "main") if convoy_list else "main"

    # ---- Terrain plane ----
    xs = np.linspace(-620, 620, 4)
    ys = np.linspace(-320, 320, 4)
    XX, YY = np.meshgrid(xs, ys)
    ZZ = np.zeros_like(XX)
    ax.plot_surface(XX, YY, ZZ, color=_TERRAIN_COLOR, alpha=0.55, linewidth=0, zorder=0)

    # ---- Routes ----
    for route_id, wpts in route_waypoints.items():
        pts = _route_pts(wpts, z=0.6)
        color = _ROUTE_ACTIVE if route_id == active_route else _ROUTE_DIM
        alpha = 0.9 if route_id == active_route else 0.2
        lw = 2.5 if route_id == active_route else 0.8
        ax.plot(pts[:, 0], pts[:, 1], pts[:, 2], color=color, lw=lw, alpha=alpha, zorder=1)

    # ---- Edge nodes (server racks) ----
    edge_positions: dict[str, tuple] = {}
    for edge in frame.get("edges", []):
        p = edge["pose"]
        x, y, z = float(p["x"]), float(p["y"]), float(p.get("z", 1.2))
        edge_positions[edge["id"]] = (x, y, z)
        quads = _box_quads(x, y, z, w=3.5, d=2.0, h=4.5)
        col = Poly3DCollection(quads, facecolor=_EDGE_COLOR, edgecolor="#2060A0", alpha=0.80, linewidth=0.4)
        ax.add_collection3d(col)

    # ---- Convoy (Carter-style box) ----
    convoy_positions: dict[str, tuple] = {}
    for v in convoy_list:
        p = v["pose"]
        x, y, z = float(p["x"]), float(p["y"]), float(p.get("z", 0.8))
        convoy_positions[v["id"]] = (x, y, z)
        quads = _box_quads(x, y, z - 0.8, w=6.0, d=3.5, h=2.5)
        col = Poly3DCollection(quads, facecolor=_CONVOY_COLOR, edgecolor="#888888", alpha=0.92, linewidth=0.6)
        ax.add_collection3d(col)
        # Cabin
        cab = _box_quads(x + 1.5, y, z + 1.7, w=2.5, d=3.2, h=1.8)
        col2 = Poly3DCollection(cab, facecolor="#CCCCCC", edgecolor="#888888", alpha=0.85, linewidth=0.4)
        ax.add_collection3d(col2)

    # ---- Drones (Neo11 hexcopters + Crazyflie CF2X scouts) ----
    drone_positions: dict[str, tuple] = {}
    for drone in frame.get("drones", []):
        p = drone["pose"]
        x, y, z = float(p["x"]), float(p["y"]), float(p.get("z", 18.0))
        drone_positions[drone["id"]] = (x, y, z)
        is_parent = drone["tier"] == "PARENT"
        size = 4.5 if is_parent else 2.2
        color = _PARENT_COLOR if is_parent else _SMALL_COLOR
        rotor_angles = (30, 90, 150, 210, 270, 330) if is_parent else (45, 135, 225, 315)
        quads = _drone_body_quads(x, y, z, size=size, rotor_angles=rotor_angles)
        col = Poly3DCollection(quads, facecolor=color, edgecolor="#000000", alpha=0.88, linewidth=0.3)
        ax.add_collection3d(col)
        # Rotor discs — flat circles at arm tips
        for angle in rotor_angles:
            rad = math.radians(angle)
            rx = x + size * 1.4 * math.cos(rad)
            ry = y + size * 1.4 * math.sin(rad)
            rz = z + size * 0.1
            theta = np.linspace(0, 2 * math.pi, 16)
            r_disc = size * 0.55
            ax.plot(rx + r_disc * np.cos(theta), ry + r_disc * np.sin(theta), rz,
                    color=color, alpha=0.35, linewidth=1.0)

    # ---- Comms links ----
    all_positions = {**edge_positions, **convoy_positions, **drone_positions}
    for link in frame.get("links", []):
        src = all_positions.get(link["from_id"])
        dst = all_positions.get(link["to_id"])
        if src is None or dst is None:
            continue
        color = _LINK_WIFI if link.get("type") == "WIFI_MESH" else _LINK_LORA
        q = float(link.get("quality", 0.5))
        ax.plot([src[0], dst[0]], [src[1], dst[1]], [src[2], dst[2]],
                color=color, alpha=0.12 + 0.18 * q, linewidth=0.7, zorder=3)

    # ---- Threats ----
    for threat in frame.get("threats", []):
        p = threat["pose"]
        x, y, z = float(p["x"]), float(p["y"]), float(p.get("z", 0.0))
        # Pulsing sphere-like marker
        for r, alpha in [(12, 0.10), (8, 0.18), (4, 0.45)]:
            u = np.linspace(0, 2 * math.pi, 20)
            v = np.linspace(0, math.pi, 10)
            sx = x + r * np.outer(np.cos(u), np.sin(v))
            sy = y + r * np.outer(np.sin(u), np.sin(v))
            sz = z + r * np.outer(np.ones(20), np.cos(v))
            ax.plot_surface(sx, sy, sz, color=_THREAT_COLOR, alpha=alpha, linewidth=0)
        # Crosshair lines
        ax.plot([x - 20, x + 20], [y, y], [z + 4, z + 4],
                color=_THREAT_COLOR, linewidth=1.5, alpha=0.9, zorder=5)
        ax.plot([x, x], [y - 20, y + 20], [z + 4, z + 4],
                color=_THREAT_COLOR, linewidth=1.5, alpha=0.9, zorder=5)

    # ---- HUD overlay ----
    t_val = float(frame.get("t", 0.0))
    threats_n = len(frame.get("threats", []))
    links_n = len(frame.get("links", []))
    compute_events = frame.get("compute_events", [])
    dropped = sum(1 for e in compute_events if e.get("dropped"))
    hud = (
        f"HADES Phase 2  |  t={t_val:05.1f}s  |  route: {active_route}  |  "
        f"threats: {threats_n}  |  links: {links_n}  |  "
        f"compute: {len(compute_events)}  drop: {dropped}"
    )
    fig.text(0.02, 0.97, hud, color="white", fontsize=9, fontfamily="monospace",
             va="top", bbox=dict(boxstyle="square,pad=0.3", fc="#000000CC", ec="none"))

    # Legend
    legend_items = [
        mpatches.Patch(color=_PARENT_COLOR, label="Parent drone (Neo11 hexcopter)"),
        mpatches.Patch(color=_SMALL_COLOR,  label="Small drone (CF2X Isaac)"),
        mpatches.Patch(color=_CONVOY_COLOR, label="Convoy (Carter)"),
        mpatches.Patch(color=_EDGE_COLOR,   label="Edge node (Server 1U)"),
        mpatches.Patch(color=_THREAT_COLOR, label="Threat zone"),
        mpatches.Patch(color=_LINK_WIFI,    label="WiFi mesh link"),
        mpatches.Patch(color=_LINK_LORA,    label="LoRa link"),
    ]
    ax.legend(handles=legend_items, loc="lower left", fontsize=7,
              facecolor="#111518", edgecolor="#333333", labelcolor="white",
              framealpha=0.85, ncol=2)

    plt.tight_layout(pad=0)
    fig.savefig(str(out_path), dpi=dpi, bbox_inches="tight", facecolor=_BG_COLOR)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Record Phase 2 demo (3D matplotlib render)")
    p.add_argument("--duration-s", type=float, default=30.0)
    p.add_argument("--out-dir", type=Path, default=Path("/opt/hades/recordings"))
    p.add_argument("--fps", type=int, default=10)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir: Path = args.out_dir
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = out_dir / "phase2_demo.mp4"
    log_path = out_dir / "phase2_demo.log"

    # Import route waypoints
    from hades.config import ROUTE_WAYPOINTS

    publisher = Track2SimPublisher(stub=True)
    total_ticks = int(args.duration_s * args.fps)
    log_lines: list[str] = []

    print(f"[HADES] rendering {args.duration_s}s @ {args.fps} Hz = {total_ticks} frames", flush=True)
    t0 = time.monotonic()

    for tick in range(total_ticks):
        t = tick / args.fps
        frame = publisher.frame_at(t)
        frame_dict = frame.to_full_dict()

        line = summarize_frame(frame_dict)
        log_lines.append(line)
        print(line, flush=True)

        out_path = frames_dir / f"frame_{tick:04d}.png"
        render_frame(frame_dict, out_path, ROUTE_WAYPOINTS)

    elapsed = time.monotonic() - t0
    print(f"[HADES] rendered {total_ticks} frames in {elapsed:.1f}s ({total_ticks/elapsed:.1f} fps)", flush=True)

    # Encode to mp4
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(args.fps),
        "-i", str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        str(mp4_path),
    ]
    print(f"[HADES] encoding: {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)

    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"[HADES] video  -> {mp4_path}", flush=True)
    print(f"[HADES] log    -> {log_path}", flush=True)


if __name__ == "__main__":
    main()
