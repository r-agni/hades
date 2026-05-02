/**
 * HADES side panel and HUD rendering module.
 * Exports: HADESPanel.update(frame)
 */
(function (global) {
  'use strict';

  const latHistory = {};
  const offloadKeys = new Set();
  let offloadTimes = [];

  const $ = function (id) { return document.getElementById(id); };

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function battClass(pct) { return pct > 50 ? '' : pct > 20 ? 'warn' : 'crit'; }
  function loadClass(load) {
    const p = load * 100;
    return p < 60 ? '' : p < 85 ? 'high' : 'crit';
  }
  function loadColor(load) {
    return load < 0.6 ? '#3ed07a' : load < 0.85 ? '#e7b84e' : '#ff5a52';
  }

  function drawSparkline(canvasEl, data) {
    if (!canvasEl || data.length < 2) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvasEl.offsetWidth || 100;
    const H = canvasEl.offsetHeight || 30;
    canvasEl.width = W * dpr;
    canvasEl.height = H * dpr;
    const c = canvasEl.getContext('2d');
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, W, H);

    const mn = Math.min.apply(null, data) * 0.8;
    const mx = Math.max.apply(null, data) * 1.2 + 0.001;
    const sy = function (v) { return H - ((v - mn) / (mx - mn)) * H * 0.82 - H * 0.08; };
    const sx = function (i) { return (i / (data.length - 1)) * W; };

    c.beginPath();
    data.forEach(function (v, i) {
      if (i === 0) c.moveTo(sx(i), sy(v));
      else c.lineTo(sx(i), sy(v));
    });
    c.strokeStyle = '#5fb3ff';
    c.lineWidth = 1.5;
    c.stroke();
    c.lineTo(sx(data.length - 1), H);
    c.lineTo(0, H);
    c.closePath();
    c.fillStyle = 'rgba(95,179,255,.12)';
    c.fill();
  }

  function updateHUD(frame, threatActive) {
    const parents = (frame.drones || []).filter(function (d) { return d.tier === 'PARENT'; });
    $('hudTime').textContent = frame.t.toFixed(1) + 's';

    if (parents.length) {
      const minBatt = Math.min.apply(null, parents.map(function (d) { return d.battery_pct; }));
      const battEl = $('hudBatt');
      battEl.textContent = minBatt.toFixed(1) + '%';
      battEl.className = 'hud-val ' + (minBatt > 50 ? 'green' : minBatt > 20 ? 'orange' : 'red');
    }

    const allLat = Object.values(latHistory).reduce(function (a, b) { return a.concat(b); }, []);
    const avgLat = allLat.length
      ? (allLat.reduce(function (a, b) { return a + b; }, 0) / allLat.length).toFixed(1)
      : '--';
    $('hudLat').textContent = avgLat + 'ms';

    const now = Date.now();
    offloadTimes = offloadTimes.filter(function (o) { return now - o.ts < 60000; });
    $('hudOffloads').textContent = offloadTimes.length;

    const pill = $('threatPill');
    pill.className = 'threat-pill ' + (threatActive ? 'active' : 'clear');
    pill.textContent = threatActive ? 'THREAT' : 'CLEAR';
  }

  function updateThreatBanner(investigating) {
    const banner = $('threatBanner');
    if (investigating.length > 0) {
      banner.className = 'threat-banner show';
      banner.textContent = 'THREAT ACTIVE - investigating: ' +
        investigating.map(function (d) { return d.id; }).join(', ');
    } else {
      banner.className = 'threat-banner';
      banner.textContent = '';
    }
  }

  function updateParentCards(parents) {
    const el = $('parentCards');
    el.innerHTML = '';
    parents.forEach(function (d) {
      const history = (latHistory[d.id] || []).slice(-15);
      const avgMs = history.length
        ? (history.reduce(function (a, b) { return a + b; }, 0) / history.length).toFixed(0)
        : '--';

      const card = document.createElement('div');
      card.className = 'drone-card';
      card.innerHTML =
        '<div class="drone-card-header">' +
          '<span class="drone-id">' + d.id + '</span>' +
          '<span class="badge parent">PARENT</span>' +
        '</div>' +
        '<div class="metric-row"><span>Battery</span>' +
          '<div class="bar-track"><div class="bar-fill batt ' + battClass(d.battery_pct) + '" style="width:' + clamp(d.battery_pct, 0, 100) + '%"></div></div>' +
          '<span class="bar-val">' + d.battery_pct.toFixed(1) + '%</span>' +
        '</div>' +
        '<div class="metric-row"><span>Compute</span>' +
          '<div class="bar-track"><div class="bar-fill load ' + loadClass(d.compute_load) + '" style="width:' + clamp(d.compute_load * 100, 0, 100) + '%"></div></div>' +
          '<span class="bar-val">' + Math.round(d.compute_load * 100) + '%</span>' +
        '</div>' +
        '<div class="spark-wrap">' +
          '<div class="spark-label">Offload latency avg ' + avgMs + 'ms</div>' +
          '<canvas class="spark" id="spark_' + d.id + '" height="30"></canvas>' +
        '</div>';
      el.appendChild(card);

      requestAnimationFrame(function () {
        const canvas = document.getElementById('spark_' + d.id);
        if (canvas) drawSparkline(canvas, history);
      });
    });
  }

  function updateScenario(frame) {
    const phaseEl = $('scenarioPhase');
    const alertsEl = $('scenarioAlerts');
    if (!phaseEl || !alertsEl) return;
    phaseEl.textContent = (frame.scenario_phase || 'normal_escort').replace(/_/g, ' ');
    alertsEl.innerHTML = '';
    (frame.alerts || []).forEach(function (alert) {
      const chip = document.createElement('span');
      chip.textContent = alert;
      alertsEl.appendChild(chip);
    });
    if (!(frame.alerts || []).length) {
      const chip = document.createElement('span');
      chip.textContent = 'NOMINAL';
      alertsEl.appendChild(chip);
    }
  }

  function updateSmallCards(smalls) {
    const el = $('smallCards');
    el.innerHTML = '';
    smalls.forEach(function (d) {
      const isThreat = d.current_task === 'investigate_threat';
      const isRecover = d.current_task === 'recover';
      const taskClass = isThreat ? 'threat' : isRecover ? 'recover' : '';
      const card = document.createElement('div');
      card.className = 'drone-card';
      card.innerHTML =
        '<div class="drone-card-header">' +
          '<span class="drone-id small">' + d.id + '</span>' +
          '<span class="badge small">SML</span>' +
        '</div>' +
        '<div class="drone-task ' + taskClass + '">' + d.current_task + '</div>' +
        '<div class="metric-row" style="margin-top:4px"><span>Batt</span>' +
          '<div class="bar-track"><div class="bar-fill batt ' + battClass(d.battery_pct) + '" style="width:' + clamp(d.battery_pct, 0, 100) + '%"></div></div>' +
          '<span class="bar-val">' + Math.round(d.battery_pct) + '%</span>' +
        '</div>';
      el.appendChild(card);
    });
  }

  function updateEdgeHeatmap(edges) {
    const alive = edges.filter(function (e) { return e.alive; }).length;
    $('edgeAliveCount').textContent = '(' + alive + '/' + edges.length + ' alive)';

    const el = $('edgeHeatmap');
    el.innerHTML = '';
    edges.forEach(function (edge) {
      const cell = document.createElement('div');
      const load = edge.compute_load || 0;
      const col = edge.alive ? loadColor(load) : '#536477';
      cell.className = 'edge-cell';
      cell.style.background = col + (edge.alive ? 'cc' : '55');
      cell.innerHTML =
        '<div class="edge-cell-tip">' +
          edge.id + '<br>' +
          Math.round(load * 100) + '% load<br>' +
          (edge.battery_pct || 0).toFixed(0) + '% batt' +
        '</div>';
      el.appendChild(cell);
    });
  }

  function updateEventLog(events) {
    const el = $('eventLog');
    el.innerHTML = '';
    events.slice().reverse().slice(0, 18).forEach(function (ev) {
      const isEdge = ev.chosen_target.indexOf('edge_') === 0;
      const isPeer = ev.chosen_target.indexOf('parent_') === 0 && ev.chosen_target !== ev.parent_id;
      const targetClass = isEdge ? 'edge' : isPeer ? 'peer' : 'self';
      const row = document.createElement('div');
      row.className = 'ev';
      row.innerHTML =
        '<span class="ev-pid">' + ev.parent_id + '</span>' +
        '<span class="ev-arr">&gt;</span>' +
        '<span class="ev-tgt ' + targetClass + '">' + ev.chosen_target + '</span>' +
        '<span class="ev-meta">' + ev.reason + '&nbsp;<span class="ev-actual">' + ev.actual_latency_ms + 'ms</span></span>';
      el.appendChild(row);
    });
  }

  function updateConvoy(convoy) {
    if (!convoy || !convoy.length) return;
    const pct = convoy[0].route_progress_pct || 0;
    $('convoyBar').style.width = clamp(pct, 0, 100) + '%';
    $('convoyPct').textContent = pct.toFixed(1) + '%';
    $('convoySpeed').textContent = (convoy[0].speed_mps || 0).toFixed(1) + ' m/s';
  }

  function updateHistory(events) {
    events.forEach(function (ev) {
      if (!latHistory[ev.parent_id]) latHistory[ev.parent_id] = [];
      const history = latHistory[ev.parent_id];
      if (!history.length || history[history.length - 1] !== ev.actual_latency_ms) {
        history.push(ev.actual_latency_ms);
        if (history.length > 60) history.shift();
      }

      const key = ev.task_id + ev.parent_id;
      if (!offloadKeys.has(key)) {
        offloadKeys.add(key);
        offloadTimes.push({ key: key, ts: Date.now() });
      }
    });
  }

  function updatePanel(frame) {
    if (!frame) return;

    const drones = frame.drones || [];
    const parents = drones.filter(function (d) { return d.tier === 'PARENT'; });
    const smalls = drones.filter(function (d) { return d.tier === 'SMALL'; });
    const events = frame.events || [];
    const investigating = smalls.filter(function (d) {
      return d.current_task === 'investigate_threat';
    });

    updateHistory(events);
    updateScenario(frame);
    updateHUD(frame, investigating.length > 0);
    updateThreatBanner(investigating);
    updateParentCards(parents);
    updateSmallCards(smalls);
    updateEdgeHeatmap(frame.edges || []);
    updateEventLog(events);
    updateConvoy(frame.convoy);
  }

  global.HADESPanel = { update: updatePanel };
}(window));
