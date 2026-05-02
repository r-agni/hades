/**
 * HADES tactical map canvas rendering module.
 * Exports: HADESTactical.init(canvasEl), HADESTactical.setFrame(frame)
 */
(function (global) {
  'use strict';

  const WORLD = { xMin: -230, xMax: 230, yMin: -110, yMax: 110 };
  const ROUTE_POINTS = [
    [-210, -42],
    [-170, -54],
    [-125, -26],
    [-83, 16],
    [-31, 28],
    [18, 7],
    [56, -31],
    [112, -22],
    [162, 18],
    [208, 31],
  ];
  const COLORS = {
    asphalt: '#2b3033',
    shoulder: '#8b7f62',
    lane: '#d8c16a',
    parent: '#5fb3ff',
    small: '#d7dee7',
    edge: '#3ed07a',
    threat: '#ff5a52',
    recover: '#e7b84e',
    payload: '#7dffb7',
  };

  let canvas;
  let ctx;
  let frame = null;
  let animT = 0;
  let dashOffset = 0;
  let terrainCache = null;
  let terrainSize = { w: 0, h: 0 };
  let particles = [];
  let viewport = { scale: 1, xMin: WORLD.xMin, yMax: WORLD.yMax, w: 1, h: 1 };

  function init(canvasEl) {
    canvas = canvasEl;
    ctx = canvas.getContext('2d');
    window.addEventListener('resize', resize);
    resize();
    requestAnimationFrame(loop);
  }

  function resize() {
    const r = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(r.width * dpr));
    canvas.height = Math.max(1, Math.floor(r.height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    terrainCache = null;
  }

  function setFrame(nextFrame) {
    frame = nextFrame;
    spawnParticlesForFrame();
  }

  function updateViewport(W, H) {
    const lead = frame && frame.convoy && frame.convoy.length ? frame.convoy[0].pose : { x: 0, y: 0 };
    const targetW = 310;
    const targetH = targetW * (H / Math.max(W, 1));
    const worldW = Math.min(WORLD.xMax - WORLD.xMin, targetW);
    const worldH = Math.min(WORLD.yMax - WORLD.yMin, Math.max(150, targetH));
    const cx = clamp(lead.x, WORLD.xMin + worldW / 2, WORLD.xMax - worldW / 2);
    const cy = clamp(lead.y, WORLD.yMin + worldH / 2, WORLD.yMax - worldH / 2);
    const scale = Math.min(W / worldW, H / worldH);
    viewport = {
      scale: scale,
      xMin: cx - worldW / 2,
      yMax: cy + worldH / 2,
      w: W,
      h: H,
    };
  }

  function w2s(p) {
    return {
      x: (p.x - viewport.xMin) * viewport.scale,
      y: (viewport.yMax - p.y) * viewport.scale,
    };
  }

  function metersToPx(m) {
    return m * viewport.scale;
  }

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function hash01(i, salt) {
    const v = Math.sin(i * 127.1 + salt * 311.7) * 43758.5453;
    return v - Math.floor(v);
  }

  function buildTerrain(W, H) {
    const oc = document.createElement('canvas');
    oc.width = W;
    oc.height = H;
    const c = oc.getContext('2d');

    const ground = c.createLinearGradient(0, 0, W, H);
    ground.addColorStop(0, '#6f755f');
    ground.addColorStop(0.35, '#9c936f');
    ground.addColorStop(0.68, '#b49b69');
    ground.addColorStop(1, '#6c7467');
    c.fillStyle = ground;
    c.fillRect(0, 0, W, H);

    for (let i = 0; i < 900; i++) {
      const x = hash01(i, 1) * W;
      const y = hash01(i, 2) * H;
      const r = 0.6 + hash01(i, 3) * 2.8;
      const tone = Math.floor(70 + hash01(i, 4) * 70);
      const alpha = 0.035 + hash01(i, 5) * 0.07;
      c.fillStyle = 'rgba(' + tone + ',' + Math.floor(tone * .9) + ',' + Math.floor(tone * .65) + ',' + alpha + ')';
      c.beginPath();
      c.ellipse(x, y, r * 1.8, r, hash01(i, 6) * Math.PI, 0, Math.PI * 2);
      c.fill();
    }

    drawTerrainWash(c, W, H, H * 0.22, 0.9, 'rgba(70,92,91,.20)');
    drawTerrainWash(c, W, H, H * 0.72, -0.65, 'rgba(78,62,45,.18)');
    drawContourBands(c, W, H);
    drawScrub(c, W, H);
    drawMapGrid(c, W, H);

    const vignette = c.createRadialGradient(W * 0.5, H * 0.48, 0, W * 0.5, H * 0.48, Math.max(W, H) * 0.72);
    vignette.addColorStop(0, 'rgba(255,255,255,0)');
    vignette.addColorStop(1, 'rgba(0,0,0,.28)');
    c.fillStyle = vignette;
    c.fillRect(0, 0, W, H);

    return oc;
  }

  function drawTerrainWash(c, W, H, baseY, slope, color) {
    c.save();
    c.strokeStyle = color;
    c.lineWidth = 10;
    c.lineCap = 'round';
    c.beginPath();
    for (let i = 0; i <= 16; i++) {
      const x = (i / 16) * W;
      const y = baseY + slope * (x - W / 2) * 0.12 + Math.sin(i * 1.3) * 18;
      if (i === 0) c.moveTo(x, y);
      else c.lineTo(x, y);
    }
    c.stroke();
    c.lineWidth = 2;
    c.strokeStyle = 'rgba(255,255,255,.08)';
    c.stroke();
    c.restore();
  }

  function drawContourBands(c, W, H) {
    c.save();
    c.strokeStyle = 'rgba(34,44,38,.13)';
    c.lineWidth = 1;
    for (let band = 0; band < 12; band++) {
      const y0 = H * (0.10 + band * 0.075);
      c.beginPath();
      for (let i = 0; i <= 24; i++) {
        const x = (i / 24) * W;
        const y = y0 + Math.sin(i * 0.9 + band) * 5 + Math.cos(i * 0.27 + band * 2) * 7;
        if (i === 0) c.moveTo(x, y);
        else c.lineTo(x, y);
      }
      c.stroke();
    }
    c.restore();
  }

  function drawScrub(c, W, H) {
    c.save();
    for (let i = 0; i < 115; i++) {
      const x = hash01(i, 20) * W;
      const y = hash01(i, 21) * H;
      const r = 1.4 + hash01(i, 22) * 2.8;
      c.fillStyle = hash01(i, 23) > 0.5 ? 'rgba(52,75,54,.38)' : 'rgba(90,82,52,.32)';
      c.beginPath();
      c.ellipse(x, y, r * 1.5, r, hash01(i, 24) * Math.PI, 0, Math.PI * 2);
      c.fill();
    }
    c.restore();
  }

  function drawMapGrid(c, W, H) {
    c.save();
    c.strokeStyle = 'rgba(255,255,255,.045)';
    c.lineWidth = 1;
    c.setLineDash([3, 8]);
    for (let x = 0; x <= W; x += 72) {
      c.beginPath();
      c.moveTo(x, 0);
      c.lineTo(x, H);
      c.stroke();
    }
    for (let y = 0; y <= H; y += 72) {
      c.beginPath();
      c.moveTo(0, y);
      c.lineTo(W, y);
      c.stroke();
    }
    c.restore();
  }

  function line(c, a, b) {
    c.beginPath();
    c.moveTo(a.x, a.y);
    c.lineTo(b.x, b.y);
    c.stroke();
  }

  function routePath(c, offsetY) {
    c.beginPath();
    ROUTE_POINTS.forEach(function (pt, idx) {
      const p = w2s({ x: pt[0], y: pt[1] + (offsetY || 0) });
      if (idx === 0) c.moveTo(p.x, p.y);
      else c.lineTo(p.x, p.y);
    });
  }

  function roundedRect(c, x, y, w, h, r, fill, stroke) {
    c.beginPath();
    c.moveTo(x + r, y);
    c.lineTo(x + w - r, y);
    c.arc(x + w - r, y + r, r, -Math.PI / 2, 0);
    c.lineTo(x + w, y + h - r);
    c.arc(x + w - r, y + h - r, r, 0, Math.PI / 2);
    c.lineTo(x + r, y + h);
    c.arc(x + r, y + h - r, r, Math.PI / 2, Math.PI);
    c.lineTo(x, y + r);
    c.arc(x + r, y + r, r, Math.PI, -Math.PI / 2);
    c.closePath();
    if (fill) {
      c.fillStyle = fill;
      c.fill();
    }
    if (stroke) {
      c.strokeStyle = stroke;
      c.stroke();
    }
  }

  function drawRoad(c) {
    const roadW = metersToPx(22);
    const shoulderW = metersToPx(34);

    c.save();
    c.lineCap = 'round';
    c.lineJoin = 'round';
    c.strokeStyle = 'rgba(42,36,28,.38)';
    c.lineWidth = shoulderW + 10;
    routePath(c, 0);
    c.stroke();

    c.strokeStyle = COLORS.shoulder;
    c.lineWidth = shoulderW;
    routePath(c, 0);
    c.stroke();

    c.strokeStyle = COLORS.asphalt;
    c.lineWidth = roadW;
    routePath(c, 0);
    c.stroke();

    c.strokeStyle = 'rgba(255,255,255,.20)';
    c.lineWidth = 1;
    [-10.5, 10.5].forEach(function (y) {
      routePath(c, y);
      c.stroke();
    });

    c.setLineDash([metersToPx(13), metersToPx(9)]);
    c.lineDashOffset = -dashOffset * 0.5;
    c.strokeStyle = COLORS.lane;
    c.lineWidth = 2;
    routePath(c, 0);
    c.stroke();
    c.setLineDash([]);

    c.strokeStyle = 'rgba(0,0,0,.18)';
    c.lineWidth = 1.4;
    [-4.2, 4.2].forEach(function (y) {
      c.setLineDash([metersToPx(20), metersToPx(11)]);
      routePath(c, y);
      c.stroke();
    });
    c.restore();
  }

  function drawRangeRings(c, edges) {
    c.save();
    edges.forEach(function (edge) {
      if (!edge.alive) return;
      const p = w2s(edge.pose);
      const r = metersToPx(edge.wifi_radius_m || 150);
      const grad = c.createRadialGradient(p.x, p.y, 0, p.x, p.y, r);
      grad.addColorStop(0, 'rgba(62,208,122,.035)');
      grad.addColorStop(0.62, 'rgba(62,208,122,.035)');
      grad.addColorStop(1, 'rgba(62,208,122,0)');
      c.fillStyle = grad;
      c.beginPath();
      c.arc(p.x, p.y, r, 0, Math.PI * 2);
      c.fill();
      c.strokeStyle = 'rgba(62,208,122,.10)';
      c.lineWidth = 1;
      c.setLineDash([4, 8]);
      c.stroke();
      c.setLineDash([]);
    });
    c.restore();
  }

  function qualityColor(q) {
    if (q >= 0.6) return '#3ed07a';
    if (q >= 0.3) return '#e7b84e';
    return '#ff5a52';
  }

  function loadColor(load) {
    if (load < 0.6) return COLORS.edge;
    if (load < 0.85) return COLORS.recover;
    return COLORS.threat;
  }

  function drawCurve(c, pa, pb, lift) {
    const mx = (pa.x + pb.x) / 2;
    const my = (pa.y + pb.y) / 2 - lift;
    c.beginPath();
    c.moveTo(pa.x, pa.y);
    c.quadraticCurveTo(mx, my, pb.x, pb.y);
    c.stroke();
  }

  function drawLinkStroke(c, pa, pb, lift, stroke, width, alpha, dash) {
    c.save();
    c.globalAlpha = alpha;
    c.strokeStyle = stroke;
    c.lineWidth = width;
    c.lineCap = 'round';
    if (dash) {
      c.setLineDash(dash);
      c.lineDashOffset = -dashOffset;
    }
    drawCurve(c, pa, pb, lift);
    c.restore();
  }

  function drawLinks(c, allActors) {
    const links = frame.links || [];
    c.save();
    links.forEach(function (link) {
      const a = allActors.find(function (actor) { return actor.id === link.from_id; });
      const b = allActors.find(function (actor) { return actor.id === link.to_id; });
      if (!a || !b) return;

      const pa = w2s(a.pose);
      const pb = w2s(b.pose);
      const dist = Math.hypot(pa.x - pb.x, pa.y - pb.y);
      const lift = clamp(dist * 0.08, 7, 32);

      if (link.type === 'LORA') {
        drawLinkStroke(c, pa, pb, lift, 'rgba(0,0,0,.78)', 4.5, 0.72, [6, 8]);
        drawLinkStroke(c, pa, pb, lift, '#ff2f2a', 2.2, 0.55 + link.quality * 0.42, [6, 8]);
      } else if (link.active_payload) {
        drawLinkStroke(c, pa, pb, lift * 0.6, 'rgba(0,0,0,.86)', 7, 0.78);
        c.save();
        c.globalAlpha = 0.95;
        c.strokeStyle = COLORS.payload;
        c.lineWidth = 4.2;
        c.lineCap = 'round';
        c.shadowBlur = 18;
        c.shadowColor = COLORS.payload;
        drawCurve(c, pa, pb, lift * 0.6);
        c.restore();
        drawLinkStroke(c, pa, pb, lift * 0.6, '#e9fff3', 1.2, 0.9);
      } else {
        drawLinkStroke(c, pa, pb, lift * 0.45, 'rgba(0,0,0,.70)', 4.2, 0.62);
        drawLinkStroke(
          c,
          pa,
          pb,
          lift * 0.45,
          qualityColor(link.quality),
          link.quality > 0.5 ? 2.4 : 1.8,
          0.34 + link.quality * 0.48
        );
      }
    });
    c.restore();
  }

  function drawParticles(c) {
    c.save();
    particles.forEach(function (p) {
      const a = w2s(p.from);
      const b = w2s(p.to);
      const x = a.x + (b.x - a.x) * p.t;
      const y = a.y + (b.y - a.y) * p.t - Math.sin(p.t * Math.PI) * 9;
      const alpha = Math.max(0, 1 - Math.abs(p.t - 0.5) * 1.6);
      c.globalAlpha = alpha * 0.95;
      c.shadowBlur = 16;
      c.shadowColor = COLORS.payload;
      c.strokeStyle = 'rgba(0,0,0,.75)';
      c.lineWidth = 2;
      c.fillStyle = COLORS.payload;
      c.beginPath();
      c.arc(x, y, 4.1, 0, Math.PI * 2);
      c.stroke();
      c.fill();
      c.fillStyle = '#f0fff5';
      c.beginPath();
      c.arc(x - 1.1, y - 1.1, 1.25, 0, Math.PI * 2);
      c.fill();
    });
    c.restore();
  }

  function spawnParticles(from, to) {
    for (let i = 0; i < 3; i++) {
      particles.push({
        from: from,
        to: to,
        t: i * 0.28,
        speed: 0.010 + Math.random() * 0.006,
      });
    }
  }

  function spawnParticlesForFrame() {
    if (!frame) return;
    const actors = [].concat(frame.drones || [], frame.edges || []);
    (frame.links || []).forEach(function (link) {
      if (!link.active_payload) return;
      const a = actors.find(function (actor) { return actor.id === link.from_id; });
      const b = actors.find(function (actor) { return actor.id === link.to_id; });
      if (a && b) spawnParticles(a.pose, b.pose);
    });
  }

  function tickParticles() {
    particles = particles.filter(function (p) {
      p.t += p.speed;
      return p.t < 1;
    });
  }

  function drawAltitudeShadow(c, pose, baseR) {
    const p = w2s(pose);
    const z = pose.z || 0;
    const offset = clamp(z * 0.18, 1, 8);
    const r = baseR + z * 0.11;
    c.save();
    c.fillStyle = 'rgba(0,0,0,.28)';
    c.beginPath();
    c.ellipse(p.x + offset, p.y + offset * 1.25, r, r * 0.42, 0, 0, Math.PI * 2);
    c.fill();
    c.restore();
  }

  function drawConvoy(c, convoy) {
    c.save();
    convoy.forEach(function (vehicle, idx) {
      const p = w2s(vehicle.pose);
      const yaw = vehicle.pose.yaw || 0;
      c.save();
      c.translate(p.x, p.y);
      c.rotate(-yaw);

      c.fillStyle = 'rgba(0,0,0,.32)';
      roundedRect(c, -18, -7, 36, 14, 3, 'rgba(0,0,0,.25)');
      c.translate(-1, -1);
      roundedRect(c, -16, -6, 32, 12, 3, idx === 0 ? '#d8c16a' : '#b7bd90', '#f2e7a5');
      roundedRect(c, 2, -5, 13, 10, 2, 'rgba(35,40,32,.45)');

      c.fillStyle = '#16191b';
      [-11, 10].forEach(function (x) {
        c.fillRect(x, -8, 6, 3);
        c.fillRect(x, 5, 6, 3);
      });
      c.strokeStyle = 'rgba(255,255,255,.28)';
      c.lineWidth = 1;
      c.beginPath();
      c.moveTo(-11, 0);
      c.lineTo(12, 0);
      c.stroke();
      c.restore();

      c.fillStyle = 'rgba(255,255,255,.68)';
      c.font = '10px Inter,sans-serif';
      c.fillText(vehicle.id, p.x + 18, p.y - 9);
    });
    c.restore();
  }

  function drawEdgeNode(c, edge) {
    const p = w2s(edge.pose);
    const load = edge.compute_load || 0;
    const col = edge.alive ? loadColor(load) : COLORS.threat;

    c.save();
    c.fillStyle = 'rgba(0,0,0,.26)';
    c.beginPath();
    c.ellipse(p.x + 2, p.y + 4, 11, 5, 0, 0, Math.PI * 2);
    c.fill();

    roundedRect(c, p.x - 9, p.y - 5, 18, 10, 2, 'rgba(22,30,27,.88)', col);
    c.fillStyle = col;
    c.fillRect(p.x - 7, p.y - 3, clamp(load, 0, 1) * 14, 2);
    c.strokeStyle = 'rgba(220,255,230,.55)';
    c.lineWidth = 1;
    c.beginPath();
    c.moveTo(p.x + 8, p.y - 4);
    c.lineTo(p.x + 8, p.y - 18);
    c.stroke();
    c.beginPath();
    c.arc(p.x + 8, p.y - 18, 2, 0, Math.PI * 2);
    c.fillStyle = col;
    c.fill();

    if (!edge.alive) {
      c.strokeStyle = COLORS.threat;
      c.lineWidth = 2;
      c.beginPath();
      c.moveTo(p.x - 7, p.y - 7);
      c.lineTo(p.x + 7, p.y + 7);
      c.moveTo(p.x + 7, p.y - 7);
      c.lineTo(p.x - 7, p.y + 7);
      c.stroke();
    }
    c.restore();
  }

  function drawSmallDrone(c, drone) {
    const p = w2s(drone.pose);
    const isThreat = drone.current_task === 'investigate_threat';
    const isRecover = drone.current_task === 'recover';
    const col = isThreat ? COLORS.threat : isRecover ? COLORS.recover : COLORS.small;
    const yaw = drone.pose.yaw || 0;

    drawAltitudeShadow(c, drone.pose, 4);
    c.save();
    c.translate(p.x, p.y);
    c.rotate(-yaw);
    c.strokeStyle = col;
    c.lineWidth = 1.2;
    c.globalAlpha = 0.95;
    c.beginPath();
    c.moveTo(-6, -6);
    c.lineTo(6, 6);
    c.moveTo(6, -6);
    c.lineTo(-6, 6);
    c.stroke();

    c.fillStyle = col;
    c.beginPath();
    c.arc(0, 0, 3, 0, Math.PI * 2);
    c.fill();

    [-7, 7].forEach(function (x) {
      [-7, 7].forEach(function (y) {
        c.beginPath();
        c.arc(x, y, 2.6 + Math.sin(animT * 0.45) * 0.3, 0, Math.PI * 2);
        c.stroke();
      });
    });
    c.restore();
  }

  function drawParentDrone(c, drone) {
    const p = w2s(drone.pose);
    const yaw = drone.pose.yaw || 0;
    const pulse = 0.5 + 0.5 * Math.sin(animT * 0.05);

    drawAltitudeShadow(c, drone.pose, 8);
    c.save();
    c.translate(p.x, p.y);
    c.rotate(-yaw);

    c.globalAlpha = 0.18 + pulse * 0.08;
    c.fillStyle = COLORS.parent;
    c.beginPath();
    c.arc(0, 0, 20, 0, Math.PI * 2);
    c.fill();
    c.globalAlpha = 1;

    c.strokeStyle = 'rgba(186,224,255,.75)';
    c.lineWidth = 2;
    c.beginPath();
    c.moveTo(-13, 0);
    c.lineTo(13, 0);
    c.moveTo(0, -13);
    c.lineTo(0, 13);
    c.stroke();

    roundedRect(c, -8, -5, 16, 10, 3, '#1b3d62', COLORS.parent);
    c.fillStyle = '#b9e2ff';
    c.beginPath();
    c.moveTo(9, 0);
    c.lineTo(3, -3);
    c.lineTo(3, 3);
    c.closePath();
    c.fill();

    [[-15, -15], [15, -15], [-15, 15], [15, 15]].forEach(function (r) {
      c.beginPath();
      c.arc(r[0], r[1], 4.2 + pulse * 0.7, 0, Math.PI * 2);
      c.strokeStyle = COLORS.parent;
      c.lineWidth = 1.2;
      c.stroke();
    });
    c.restore();

    c.fillStyle = 'rgba(237,242,247,.82)';
    c.font = '10px Inter,sans-serif';
    c.fillText(drone.id, p.x + 18, p.y - 12);
  }

  function drawThreatMarker(c) {
    const threats = frame.threats || [];
    if (!threats.length) return;

    const p = w2s(threats[0].pose);
    const r = 12 + Math.sin(animT * 0.08) * 3;

    c.save();
    c.strokeStyle = COLORS.threat;
    c.lineWidth = 2;
    c.globalAlpha = 0.55 + 0.35 * Math.abs(Math.sin(animT * 0.08));
    c.beginPath();
    c.arc(p.x, p.y, r, 0, Math.PI * 2);
    c.stroke();
    c.beginPath();
    c.moveTo(p.x - 7, p.y - 7);
    c.lineTo(p.x + 7, p.y + 7);
    c.moveTo(p.x + 7, p.y - 7);
    c.lineTo(p.x - 7, p.y + 7);
    c.stroke();
    c.fillStyle = COLORS.threat;
    c.font = '10px Inter,sans-serif';
    c.fillText('CONTACT ' + Math.round((threats[0].confidence || 0.9) * 100) + '%', p.x + 14, p.y - 10);
    c.restore();
  }

  function drawDust(c) {
    if (!frame || !frame.convoy || !frame.convoy.length) return;
    const lead = frame.convoy[0];
    c.save();
    for (let i = 0; i < 16; i++) {
      const yaw = lead.pose.yaw || 0;
      const back = -14 - i * 4.5;
      const lateral = Math.sin(i) * 1.3;
      const p = w2s({
        x: lead.pose.x + Math.cos(yaw) * back + Math.sin(yaw) * lateral,
        y: lead.pose.y + Math.sin(yaw) * back - Math.cos(yaw) * lateral,
      });
      const a = (0.13 - i * 0.006) * (0.65 + 0.35 * Math.sin(animT * 0.06 + i));
      c.fillStyle = 'rgba(215,194,142,' + Math.max(0, a) + ')';
      c.beginPath();
      c.ellipse(p.x, p.y + 4, 5 + i * 0.75, 2.5 + i * 0.25, 0, 0, Math.PI * 2);
      c.fill();
    }
    c.restore();
  }

  function drawSceneLabels(c) {
    c.save();
    c.fillStyle = 'rgba(255,255,255,.45)';
    c.font = '10px Inter,sans-serif';
    c.fillText('GRID A-17', 12, 18);
    c.fillText('ROUTE REDWOOD', w2s({ x: 92, y: -17 }).x, w2s({ x: 92, y: -17 }).y);
    c.restore();
  }

  function drawScenarioZones(c) {
    const phase = frame && frame.scenario_phase;
    c.save();
    if (phase === 'weak_link_zone' || phase === 'rf_jamming') {
      const a = w2s({ x: -20, y: 20 });
      const b = w2s({ x: 95, y: -72 });
      c.fillStyle = 'rgba(231,184,78,.10)';
      c.strokeStyle = 'rgba(231,184,78,.35)';
      c.setLineDash([8, 8]);
      c.lineWidth = 1.5;
      c.fillRect(a.x, a.y, b.x - a.x, b.y - a.y);
      c.strokeRect(a.x, a.y, b.x - a.x, b.y - a.y);
      c.fillStyle = 'rgba(255,230,150,.8)';
      c.font = '10px Inter,sans-serif';
      c.fillText('WEAK LINK ZONE', a.x + 8, a.y + 16);
    }
    if (phase === 'rf_jamming') {
      const p = w2s({ x: 90, y: 52 });
      const pulse = 0.5 + 0.5 * Math.sin(animT * 0.12);
      c.strokeStyle = 'rgba(255,90,82,' + (0.35 + pulse * 0.35) + ')';
      c.lineWidth = 2;
      c.setLineDash([3, 9]);
      for (let r = 22; r <= 66; r += 22) {
        c.beginPath();
        c.arc(p.x, p.y, r + pulse * 5, 0, Math.PI * 2);
        c.stroke();
      }
      c.setLineDash([]);
      c.fillStyle = COLORS.threat;
      c.font = '10px Inter,sans-serif';
      c.fillText('RF JAMMER', p.x + 14, p.y - 10);
    }
    c.restore();
  }

  function drawCallouts(c) {
    if (!frame) return;
    const alerts = frame.alerts || [];
    const lead = frame.convoy && frame.convoy.length ? w2s(frame.convoy[0].pose) : { x: 20, y: 20 };
    c.save();
    alerts.slice(0, 3).forEach(function (alert, idx) {
      const x = clamp(lead.x + 26, 16, viewport.w - 170);
      const y = clamp(lead.y - 58 + idx * 24, 16, viewport.h - 34);
      const danger = alert.indexOf('JAM') >= 0 || alert.indexOf('CONTACT') >= 0;
      const warn = alert.indexOf('LINK') >= 0 || alert.indexOf('DEAD') >= 0;
      const col = danger ? COLORS.threat : warn ? COLORS.recover : COLORS.payload;
      roundedRect(c, x, y, 150, 18, 4, 'rgba(8,11,15,.78)', col);
      c.fillStyle = col;
      c.font = '10px Inter,sans-serif';
      c.fillText(alert, x + 8, y + 12);
    });

    const latest = frame.events && frame.events.length ? frame.events[frame.events.length - 1] : null;
    if (latest) {
      const x = clamp(lead.x - 178, 16, viewport.w - 196);
      const y = clamp(lead.y + 36, 18, viewport.h - 38);
      roundedRect(c, x, y, 180, 24, 5, 'rgba(8,11,15,.78)', COLORS.payload);
      c.fillStyle = COLORS.payload;
      c.font = '10px Inter,sans-serif';
      c.fillText('OFFLOAD ' + latest.parent_id + ' > ' + latest.chosen_target + '  ' + latest.actual_latency_ms + 'ms', x + 8, y + 15);
    }
    c.restore();
  }

  function minimapPoint(pt, box) {
    return {
      x: box.x + ((pt[0] - WORLD.xMin) / (WORLD.xMax - WORLD.xMin)) * box.w,
      y: box.y + ((WORLD.yMax - pt[1]) / (WORLD.yMax - WORLD.yMin)) * box.h,
    };
  }

  function drawMiniMap(c, edges, convoy) {
    const box = { x: 14, y: 44, w: 188, h: 112 };
    c.save();
    roundedRect(c, box.x, box.y, box.w, box.h, 6, 'rgba(8,11,15,.72)', 'rgba(255,255,255,.18)');
    c.strokeStyle = 'rgba(216,193,106,.75)';
    c.lineWidth = 2;
    c.beginPath();
    ROUTE_POINTS.forEach(function (pt, idx) {
      const p = minimapPoint(pt, box);
      if (idx === 0) c.moveTo(p.x, p.y);
      else c.lineTo(p.x, p.y);
    });
    c.stroke();

    edges.forEach(function (edge) {
      const p = minimapPoint([edge.pose.x, edge.pose.y], box);
      c.fillStyle = edge.alive ? COLORS.edge : COLORS.threat;
      c.fillRect(p.x - 1.5, p.y - 1.5, 3, 3);
    });

    if (convoy && convoy.length) {
      const p = minimapPoint([convoy[0].pose.x, convoy[0].pose.y], box);
      c.fillStyle = '#fff09a';
      c.beginPath();
      c.arc(p.x, p.y, 4, 0, Math.PI * 2);
      c.fill();
    }

    c.fillStyle = 'rgba(237,242,247,.75)';
    c.font = '10px Inter,sans-serif';
    c.fillText('FULL ROUTE', box.x + 9, box.y + 15);
    c.restore();
  }

  function draw() {
    const r = canvas.getBoundingClientRect();
    const W = r.width;
    const H = r.height;
    if (W < 1 || H < 1) return;
    updateViewport(W, H);

    if (!terrainCache || terrainSize.w !== Math.floor(W) || terrainSize.h !== Math.floor(H)) {
      terrainCache = buildTerrain(Math.floor(W), Math.floor(H));
      terrainSize = { w: Math.floor(W), h: Math.floor(H) };
    }

    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(terrainCache, 0, 0, W, H);
    drawRoad(ctx);
    drawSceneLabels(ctx);

    if (!frame) return;

    const drones = frame.drones || [];
    const edges = frame.edges || [];
    const convoy = frame.convoy || [];
    const smalls = drones.filter(function (d) { return d.tier === 'SMALL'; });
    const parents = drones.filter(function (d) { return d.tier === 'PARENT'; });
    const allActors = [].concat(drones, edges, convoy);

    drawScenarioZones(ctx);
    drawDust(ctx);
    drawRangeRings(ctx, edges);
    drawLinks(ctx, allActors);
    drawParticles(ctx);
    edges.forEach(function (edge) { drawEdgeNode(ctx, edge); });
    drawConvoy(ctx, convoy);
    smalls.forEach(function (drone) { drawSmallDrone(ctx, drone); });
    parents.forEach(function (drone) { drawParentDrone(ctx, drone); });
    drawThreatMarker(ctx);
    drawCallouts(ctx);
    drawMiniMap(ctx, edges, convoy);

    animT++;
    dashOffset = (dashOffset + 0.45) % 40;
  }

  function loop() {
    tickParticles();
    draw();
    requestAnimationFrame(loop);
  }

  global.HADESTactical = { init: init, setFrame: setFrame };
}(window));
