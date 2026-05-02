"""Tiny built-in live visualizer for Phase 1."""

VIZ_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>HADES Phase 1 Viz</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #111418;
      color: #e8edf2;
    }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      border-bottom: 1px solid #2a313b;
      background: #171b21;
    }
    h1 {
      margin: 0;
      font-size: 16px;
      font-weight: 650;
      letter-spacing: 0;
    }
    .stats {
      display: flex;
      gap: 14px;
      color: #aeb8c4;
      font-size: 13px;
    }
    main {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 340px;
      min-height: 0;
    }
    canvas {
      width: 100%;
      height: 100%;
      display: block;
      background: #20242a;
    }
    aside {
      border-left: 1px solid #2a313b;
      padding: 14px;
      overflow: auto;
      background: #15191f;
    }
    .section {
      margin-bottom: 18px;
    }
    .section h2 {
      margin: 0 0 8px;
      font-size: 13px;
      color: #cfd7df;
    }
    .row {
      display: grid;
      grid-template-columns: 76px 1fr 50px;
      gap: 8px;
      align-items: center;
      font-size: 12px;
      color: #b8c1cc;
      padding: 5px 0;
      border-bottom: 1px solid rgba(255,255,255,0.05);
    }
    .bar {
      height: 6px;
      background: #2d3440;
      border-radius: 4px;
      overflow: hidden;
    }
    .bar > span {
      display: block;
      height: 100%;
      background: #46d28f;
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; grid-template-rows: 62vh auto; }
      aside { border-left: 0; border-top: 1px solid #2a313b; }
      .stats { flex-wrap: wrap; justify-content: flex-end; }
    }
  </style>
</head>
<body>
  <header>
    <h1>HADES Phase 1</h1>
    <div class="stats">
      <span id="status">connecting</span>
      <span id="time">t=0.0s</span>
      <span id="counts"></span>
    </div>
  </header>
  <main>
    <canvas id="map"></canvas>
    <aside>
      <div class="section">
        <h2>Drones</h2>
        <div id="drones"></div>
      </div>
      <div class="section">
        <h2>Edge Nodes</h2>
        <div id="edges"></div>
      </div>
    </aside>
  </main>
  <script>
    const canvas = document.getElementById("map");
    const ctx = canvas.getContext("2d");
    const statusEl = document.getElementById("status");
    const timeEl = document.getElementById("time");
    const countsEl = document.getElementById("counts");
    const dronesEl = document.getElementById("drones");
    const edgesEl = document.getElementById("edges");
    let frame = null;

    function resize() {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    }

    function worldToScreen(p) {
      const rect = canvas.getBoundingClientRect();
      const x = ((p.x + 230) / 460) * rect.width;
      const y = rect.height - ((p.y + 95) / 190) * rect.height;
      return { x, y };
    }

    function dot(p, r, color, stroke = null) {
      const s = worldToScreen(p);
      ctx.beginPath();
      ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      if (stroke) {
        ctx.strokeStyle = stroke;
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }

    function label(p, text) {
      const s = worldToScreen(p);
      ctx.fillStyle = "#d8dee6";
      ctx.font = "11px Inter, sans-serif";
      ctx.fillText(text, s.x + 8, s.y - 8);
    }

    function draw() {
      const rect = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);
      ctx.fillStyle = "#24282f";
      ctx.fillRect(0, 0, rect.width, rect.height);

      const roadA = worldToScreen({x: -215, y: -5});
      const roadB = worldToScreen({x: 215, y: 5});
      ctx.strokeStyle = "#6d737b";
      ctx.lineWidth = 18;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(roadA.x, roadA.y);
      ctx.lineTo(roadB.x, roadB.y);
      ctx.stroke();
      ctx.setLineDash([16, 12]);
      ctx.strokeStyle = "#d9c36a";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(roadA.x, (roadA.y + roadB.y) / 2);
      ctx.lineTo(roadB.x, (roadA.y + roadB.y) / 2);
      ctx.stroke();
      ctx.setLineDash([]);

      if (!frame) return;

      for (const link of frame.links) {
        const all = [...frame.drones, ...frame.edges, ...frame.convoy];
        const a = all.find(item => item.id === link.from_id);
        const b = all.find(item => item.id === link.to_id);
        if (!a || !b) continue;
        const pa = worldToScreen(a.pose);
        const pb = worldToScreen(b.pose);
        ctx.globalAlpha = 0.15 + link.quality * 0.55;
        ctx.strokeStyle = link.type === "WIFI_MESH" ? "#59d99b" : "#e25a61";
        ctx.lineWidth = link.type === "WIFI_MESH" ? 3 : 1;
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pb.x, pb.y);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      for (const edge of frame.edges) {
        const s = worldToScreen(edge.pose);
        ctx.globalAlpha = 0.08;
        ctx.beginPath();
        ctx.arc(s.x, s.y, 150 / 460 * rect.width, 0, Math.PI * 2);
        ctx.fillStyle = "#59d99b";
        ctx.fill();
        ctx.globalAlpha = 1;
        dot(edge.pose, 4, "#59d99b");
      }
      for (const vehicle of frame.convoy) {
        dot(vehicle.pose, 8, "#e7d26f", "#111418");
        label(vehicle.pose, vehicle.id);
      }
      for (const drone of frame.drones) {
        const isParent = drone.tier === "PARENT";
        dot(drone.pose, isParent ? 8 : 5, isParent ? "#70a7ff" : "#f0f4ff", "#111418");
        label(drone.pose, drone.id);
      }
    }

    function row(id, label, value, pct) {
      return `<div class="row"><span>${id}</span><span>${label}<div class="bar"><span style="width:${Math.max(0, Math.min(100, pct))}%"></span></div></span><span>${value}</span></div>`;
    }

    function renderPanel() {
      if (!frame) return;
      dronesEl.innerHTML = frame.drones.map(d => row(d.id, d.current_task, `${d.battery_pct.toFixed(1)}%`, d.battery_pct)).join("");
      edgesEl.innerHTML = frame.edges.map(e => row(e.id, `${e.compute_capacity_tops} TOPS`, `${Math.round(e.compute_load * 100)}%`, e.compute_load * 100)).join("");
      timeEl.textContent = `t=${frame.t.toFixed(1)}s`;
      countsEl.textContent = `${frame.drones.length} drones · ${frame.edges.length} edges · ${frame.convoy.length} convoy`;
    }

    function connect() {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/stream`);
      ws.onopen = () => statusEl.textContent = "live";
      ws.onclose = () => {
        statusEl.textContent = "reconnecting";
        setTimeout(connect, 1000);
      };
      ws.onerror = () => statusEl.textContent = "connection error";
      ws.onmessage = event => {
        frame = JSON.parse(event.data);
        renderPanel();
        draw();
      };
    }

    window.addEventListener("resize", resize);
    resize();
    connect();
  </script>
</body>
</html>
"""
