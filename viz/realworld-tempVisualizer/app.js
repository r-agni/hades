(function () {
  'use strict';

  const state = {
    config: null,
    map: null,
    scenario: null,
    ws: null,
    info: null,
    overlays: {
      route: null,
      gaps: [],
      edges: new Map(),
      edgeRings: new Map(),
      drones: new Map(),
      droneFov: new Map(),
      convoy: new Map(),
      links: [],
      targets: new Map(),
    },
    manualEdges: new Map(),
  };

  const els = {
    dot: document.getElementById('statusDot'),
    form: document.getElementById('scenarioForm'),
    origin: document.getElementById('originInput'),
    destination: document.getElementById('destinationInput'),
    edgeCount: document.getElementById('edgeCountInput'),
    wifi: document.getElementById('wifiInput'),
    buffer: document.getElementById('bufferInput'),
    analyze: document.getElementById('analyzeButton'),
    routeDistance: document.getElementById('routeDistance'),
    coveragePct: document.getElementById('coveragePct'),
    streamTime: document.getElementById('streamTime'),
    computeMode: document.getElementById('computeMode'),
    edgeList: document.getElementById('edgeList'),
    decisionList: document.getElementById('decisionList'),
    eventList: document.getElementById('eventList'),
    message: document.getElementById('message'),
  };

  function boot() {
    fetch('/api/realworld/config')
      .then(assertOk)
      .then(function (config) {
        state.config = config;
        els.origin.value = config.default_origin;
        els.destination.value = config.default_destination;
        els.edgeCount.value = config.default_edge_count;
        els.wifi.value = config.default_wifi_radius_m;
        els.buffer.value = config.default_search_buffer_m;
        return loadGoogle(config.google_maps_key);
      })
      .then(initMap)
      .then(function () {
        bindEvents();
        return analyze();
      })
      .catch(showError);
  }

  function loadGoogle(key) {
    return new Promise(function (resolve, reject) {
      window.__hadesMapsReady = resolve;
      const script = document.createElement('script');
      script.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(key) + '&callback=__hadesMapsReady';
      script.async = true;
      script.onerror = function () { reject(new Error('Google Maps JavaScript failed to load')); };
      document.head.appendChild(script);
    });
  }

  function initMap() {
    state.map = new google.maps.Map(document.getElementById('map'), {
      center: { lat: 34.1224, lng: -118.3004 },
      zoom: 14,
      mapTypeId: 'hybrid',
      tilt: 0,
      clickableIcons: false,
      fullscreenControl: false,
      streetViewControl: false,
      mapTypeControlOptions: {
        mapTypeIds: ['hybrid', 'satellite', 'terrain', 'roadmap'],
      },
    });
    state.info = new google.maps.InfoWindow();
  }

  function bindEvents() {
    els.form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      state.manualEdges.clear();
      analyze();
    });
  }

  function analyze() {
    setBusy(true);
    hideError();
    closeStream();
    clearScenario();

    const payload = {
      origin: els.origin.value.trim(),
      destination: els.destination.value.trim(),
      edge_count: Number(els.edgeCount.value),
      wifi_radius_m: Number(els.wifi.value),
      search_buffer_m: Number(els.buffer.value),
    };

    return fetch('/api/realworld/scenarios', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(assertOk)
      .then(function (scenario) {
        state.scenario = scenario;
        renderScenario(scenario);
        openStream(scenario.scenario_id);
      })
      .catch(showError)
      .finally(function () { setBusy(false); });
  }

  function patchEdges() {
    if (!state.scenario) return;
    const manual_edges = Array.from(state.manualEdges.values());
    setBusy(true);
    fetch('/api/realworld/scenarios/' + state.scenario.scenario_id + '/edges', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ manual_edges: manual_edges }),
    })
      .then(assertOk)
      .then(function (scenario) {
        state.scenario = scenario;
        renderScenario(scenario);
      })
      .catch(showError)
      .finally(function () { setBusy(false); });
  }

  function renderScenario(scenario) {
    const route = scenario.route.points;
    const analysis = scenario.analysis;
    els.routeDistance.textContent = formatMeters(scenario.route.distance_m);
    els.coveragePct.textContent = analysis.coverage_percent.toFixed(1) + '%';

    if (state.overlays.route) state.overlays.route.setMap(null);
    state.overlays.route = new google.maps.Polyline({
      map: state.map,
      path: route,
      strokeColor: '#efbf55',
      strokeOpacity: 0.95,
      strokeWeight: 5,
    });

    state.overlays.gaps.forEach(function (gap) { gap.setMap(null); });
    state.overlays.gaps = analysis.coverage_gaps.map(function (gap) {
      return new google.maps.Polyline({
        map: state.map,
        path: [gap.start, gap.end],
        strokeColor: '#ff625d',
        strokeOpacity: 0.95,
        strokeWeight: 7,
      });
    });

    const bounds = new google.maps.LatLngBounds();
    route.forEach(function (p) { bounds.extend(p); });
    analysis.edges.forEach(function (edge) { bounds.extend({ lat: edge.lat, lng: edge.lng }); });
    state.map.fitBounds(bounds, 56);

    renderEdges(analysis.edges, scenario.settings.wifi_radius_m);
    renderEdgeList(analysis.edges);
  }

  function renderEdges(edges, radius) {
    const nextIds = new Set();
    edges.forEach(function (edge) {
      nextIds.add(edge.id);
      const pos = { lat: edge.lat, lng: edge.lng };
      let marker = state.overlays.edges.get(edge.id);
      if (!marker) {
        marker = new google.maps.Marker({
          map: state.map,
          position: pos,
          draggable: true,
          title: edge.id,
          icon: edgeIcon(edge.manual),
          zIndex: 80,
        });
        marker.addListener('click', function () { showEdgeInfo(edge, marker); });
        marker.addListener('dragend', function () {
          const p = marker.getPosition();
          state.manualEdges.set(edge.id, { id: edge.id, lat: p.lat(), lng: p.lng() });
          patchEdges();
        });
        state.overlays.edges.set(edge.id, marker);
      }
      marker.setPosition(pos);
      marker.setIcon(edgeIcon(edge.manual));

      let ring = state.overlays.edgeRings.get(edge.id);
      if (!ring) {
        ring = new google.maps.Circle({
          map: state.map,
          strokeColor: '#45d483',
          strokeOpacity: 0.34,
          strokeWeight: 1,
          fillColor: '#45d483',
          fillOpacity: 0.055,
          clickable: false,
        });
        state.overlays.edgeRings.set(edge.id, ring);
      }
      ring.setCenter(pos);
      ring.setRadius(radius);
    });

    deleteMissing(state.overlays.edges, nextIds);
    deleteMissing(state.overlays.edgeRings, nextIds);
  }

  function openStream(scenarioId) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    state.ws = new WebSocket(proto + '://' + location.host + '/api/realworld/scenarios/' + scenarioId + '/stream');
    state.ws.onopen = function () { els.dot.className = 'status live'; };
    state.ws.onerror = function () { els.dot.className = 'status err'; };
    state.ws.onclose = function () { els.dot.className = 'status'; };
    state.ws.onmessage = function (ev) {
      const frame = JSON.parse(ev.data);
      if (frame.error) {
        showError(new Error(frame.error));
        return;
      }
      renderFrame(frame);
    };
  }

  function closeStream() {
    if (state.ws) state.ws.close();
    state.ws = null;
    els.dot.className = 'status';
  }

  function renderFrame(frame) {
    els.streamTime.textContent = frame.t.toFixed(1) + 's';
    renderActors(frame);
    renderLinks(frame);
    renderTargets(frame);
    renderDecisions(frame);
    renderEvents(frame.events || []);
  }

  function renderActors(frame) {
    const convoyIds = new Set();
    (frame.convoy || []).forEach(function (vehicle) {
      convoyIds.add(vehicle.id);
      upsertMarker(state.overlays.convoy, vehicle.id, vehicle.geo, convoyIcon(), 90);
    });
    deleteMissing(state.overlays.convoy, convoyIds);

    const droneIds = new Set();
    (frame.drones || []).forEach(function (drone) {
      droneIds.add(drone.id);
      upsertMarker(state.overlays.drones, drone.id, drone.geo, droneIcon(drone), drone.tier === 'PARENT' ? 100 : 95);

      let fov = state.overlays.droneFov.get(drone.id);
      if (!fov) {
        fov = new google.maps.Circle({
          map: state.map,
          strokeColor: drone.tier === 'PARENT' ? '#6cb7ff' : '#eef5ec',
          strokeOpacity: drone.tier === 'PARENT' ? 0.34 : 0.22,
          strokeWeight: 1,
          fillColor: drone.tier === 'PARENT' ? '#6cb7ff' : '#eef5ec',
          fillOpacity: drone.tier === 'PARENT' ? 0.045 : 0.025,
          clickable: false,
        });
        state.overlays.droneFov.set(drone.id, fov);
      }
      fov.setCenter(drone.geo);
      fov.setRadius(drone.capabilities.vision_radius_m);
    });
    deleteMissing(state.overlays.drones, droneIds);
    deleteMissing(state.overlays.droneFov, droneIds);
  }

  function renderLinks(frame) {
    state.overlays.links.forEach(function (link) { link.setMap(null); });
    state.overlays.links = [];
    const actors = {};
    [].concat(frame.drones || [], frame.edges || [], frame.convoy || []).forEach(function (actor) {
      actors[actor.id] = actor.geo;
    });
    (frame.links || []).forEach(function (link) {
      const a = actors[link.from_id];
      const b = actors[link.to_id];
      if (!a || !b) return;
      state.overlays.links.push(new google.maps.Polyline({
        map: state.map,
        path: [a, b],
        strokeColor: link.type === 'LORA' ? '#ff625d' : (link.active_payload ? '#45d483' : '#6cb7ff'),
        strokeOpacity: link.active_payload ? 0.95 : 0.38 + link.quality * 0.36,
        strokeWeight: link.active_payload ? 4 : 2,
        icons: link.type === 'LORA' ? [{ icon: { path: 'M 0,-1 0,1', strokeOpacity: 1, scale: 3 }, offset: '0', repeat: '14px' }] : undefined,
      }));
    });
  }

  function renderTargets(frame) {
    const targets = (frame.sensing && frame.sensing.targets) || [];
    const ids = new Set();
    targets.forEach(function (target) {
      ids.add(target.id);
      upsertMarker(state.overlays.targets, target.id, { lat: target.lat, lng: target.lng }, targetIcon(), 70);
    });
    deleteMissing(state.overlays.targets, ids);
  }

  function renderDecisions(frame) {
    const sensing = frame.sensing || {};
    const tracks = sensing.fused_tracks || [];
    const parents = (frame.drones || []).filter(function (d) { return d.tier === 'PARENT'; });
    els.computeMode.textContent = parents.length
      ? parents.map(function (p) { return p.compute_mode === 'edge_augmented' ? 'edge' : 'local'; }).join('/')
      : '--';
    els.decisionList.innerHTML = '';

    parents.forEach(function (parent) {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-head"><span class="card-id">' + esc(parent.id) + '</span>' +
        '<span class="pill ' + (parent.compute_mode === 'edge_augmented' ? 'edge' : 'warn') + '">' +
        esc(parent.compute_mode) + '</span></div>' +
        '<div class="metric"><span>FoV</span><strong>' + parent.capabilities.vision_radius_m.toFixed(0) + ' m</strong></div>' +
        '<div class="metric"><span>Functions</span><strong>' + esc(parent.available_functions.join(', ')) + '</strong></div>';
      els.decisionList.appendChild(card);
    });

    tracks.forEach(function (track) {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-head"><span class="card-id">' + esc(track.target_id) + '</span>' +
        '<span class="pill track">' + esc(track.status) + '</span></div>' +
        '<div class="metric"><span>Fusion</span><strong>' + esc(track.fusion_parent_id) + '</strong></div>' +
        '<div class="metric"><span>Reports</span><strong>' + track.report_count + ' / ' + Math.round(track.confidence * 100) + '%</strong></div>';
      els.decisionList.appendChild(card);
    });
  }

  function renderEdgeList(edges) {
    els.edgeList.innerHTML = '';
    edges.slice(0, 18).forEach(function (edge) {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-head"><span class="card-id">' + esc(edge.id) + '</span>' +
        '<span class="pill ' + (edge.manual ? 'manual' : '') + '">' + (edge.manual ? 'MANUAL' : 'AUTO') + '</span></div>' +
        '<div class="metric"><span>Coverage</span><strong>' + formatMeters(edge.coverage_m) + '</strong></div>' +
        '<div class="metric"><span>Latency</span><strong>' + edge.avg_latency_ms.toFixed(1) + ' ms</strong></div>' +
        '<div class="metric"><span>Score</span><strong>' + edge.score.toFixed(1) + '</strong></div>' +
        '<div class="reason">' + esc(edge.reasons[0] || '') + '</div>';
      els.edgeList.appendChild(card);
    });
  }

  function renderEvents(events) {
    els.eventList.innerHTML = '';
    events.slice().reverse().slice(0, 12).forEach(function (event) {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-head"><span class="card-id">' + esc(event.parent_id) + ' > ' + esc(event.chosen_target) + '</span>' +
        '<span class="pill">' + esc(event.reason) + '</span></div>' +
        '<div class="metric"><span>Latency</span><strong>' + event.actual_latency_ms.toFixed(1) + ' ms</strong></div>';
      els.eventList.appendChild(card);
    });
  }

  function upsertMarker(store, id, position, icon, zIndex) {
    let marker = store.get(id);
    if (!marker) {
      marker = new google.maps.Marker({ map: state.map, position: position, icon: icon, title: id, zIndex: zIndex });
      store.set(id, marker);
    }
    marker.setPosition(position);
    marker.setIcon(icon);
    return marker;
  }

  function deleteMissing(store, nextIds) {
    Array.from(store.keys()).forEach(function (id) {
      if (!nextIds.has(id)) {
        store.get(id).setMap(null);
        store.delete(id);
      }
    });
  }

  function clearScenario() {
    if (state.overlays.route) state.overlays.route.setMap(null);
    state.overlays.route = null;
    state.overlays.gaps.forEach(function (gap) { gap.setMap(null); });
    state.overlays.gaps = [];
    ['edges', 'edgeRings', 'drones', 'droneFov', 'convoy', 'targets'].forEach(function (key) {
      state.overlays[key].forEach(function (overlay) { overlay.setMap(null); });
      state.overlays[key].clear();
    });
    state.overlays.links.forEach(function (link) { link.setMap(null); });
    state.overlays.links = [];
    els.edgeList.innerHTML = '';
    els.decisionList.innerHTML = '';
    els.eventList.innerHTML = '';
  }

  function showEdgeInfo(edge, marker) {
    const html =
      '<div class="info"><strong>' + esc(edge.id) + '</strong><br>' +
      edge.reasons.map(esc).join('<br>') + '</div>';
    state.info.setContent(html);
    state.info.open({ map: state.map, anchor: marker });
  }

  function assertOk(resp) {
    return resp.json().then(function (data) {
      if (!resp.ok) {
        throw new Error(data.detail || data.error || resp.statusText);
      }
      return data;
    });
  }

  function setBusy(isBusy) {
    els.analyze.disabled = isBusy;
    els.analyze.textContent = isBusy ? 'Working' : 'Analyze';
  }

  function showError(error) {
    els.dot.className = 'status err';
    els.message.className = 'message show';
    els.message.textContent = error && error.message ? error.message : String(error);
  }

  function hideError() {
    els.message.className = 'message';
    els.message.textContent = '';
  }

  function formatMeters(meters) {
    return meters >= 1000 ? (meters / 1000).toFixed(2) + ' km' : Math.round(meters) + ' m';
  }

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }

  function edgeIcon(manual) {
    return {
      path: google.maps.SymbolPath.BACKWARD_CLOSED_ARROW,
      scale: 5,
      rotation: 180,
      fillColor: manual ? '#efbf55' : '#45d483',
      fillOpacity: 1,
      strokeColor: '#07100a',
      strokeWeight: 2,
    };
  }

  function droneIcon(drone) {
    return {
      path: google.maps.SymbolPath.CIRCLE,
      scale: drone.tier === 'PARENT' ? 7 : 4,
      fillColor: drone.tier === 'PARENT' ? '#6cb7ff' : '#eef5ec',
      fillOpacity: .95,
      strokeColor: '#07100a',
      strokeWeight: 2,
    };
  }

  function convoyIcon() {
    return {
      path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
      scale: 5,
      fillColor: '#efbf55',
      fillOpacity: 1,
      strokeColor: '#07100a',
      strokeWeight: 2,
    };
  }

  function targetIcon() {
    return {
      path: google.maps.SymbolPath.CIRCLE,
      scale: 5,
      fillColor: '#ff625d',
      fillOpacity: .9,
      strokeColor: '#ffffff',
      strokeWeight: 1,
    };
  }

  boot();
}());
