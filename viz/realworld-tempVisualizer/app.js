(function () {
  'use strict';

  const AUTO_REROUTE_DELAY_MS = 2800;
  const AUTO_REROUTE_COOLDOWN_MS = 14000;
  const FOLLOW_MAX_ZOOM = 15;
  const FOLLOW_ACTIVE_MAX_ZOOM = 13;
  const FOLLOW_MIN_ZOOM = 11;
  const FOLLOW_LOCK_ZOOM = 15;
  const FOLLOW_CAMERA_INTERVAL_MS = 450;
  const MOTION_SMOOTH_MS = 220;
  const TACTICAL_MAP_STYLES = [
    { featureType: 'all', elementType: 'labels.text.fill', stylers: [{ color: '#d7fbff' }] },
    { featureType: 'all', elementType: 'labels.text.stroke', stylers: [{ color: '#071012' }, { weight: 3 }] },
    { featureType: 'administrative', elementType: 'geometry', stylers: [{ color: '#65e8ef' }, { visibility: 'simplified' }] },
    { featureType: 'poi', stylers: [{ visibility: 'off' }] },
    { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#1c2b2f' }, { weight: 1.1 }] },
    { featureType: 'road', elementType: 'geometry.stroke', stylers: [{ color: '#65e8ef' }, { weight: .45 }] },
    { featureType: 'transit', stylers: [{ visibility: 'off' }] },
    { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#0d2634' }] },
  ];

  const state = {
    config: null,
    map: null,
    scenario: null,
    ws: null,
    info: null,
    cameraMode: 'follow',
    activePanel: 'edges',
    setupCollapsed: false,
    presentation: new URLSearchParams(window.location.search).get('presentation') === '1',
    layers: {
      routeScore: true,
      terrain: true,
      feasibility: true,
      candidates: true,
      data: true,
      vectors: true,
      search: true,
      links: true,
      detections: true,
    },
    lastFollowCameraAt: 0,
    lastRouteRevision: null,
    rerouteRequested: false,
    autoRerouteTimer: null,
    autoRerouteCooldownUntil: 0,
    overlays: {
      route: null,
      routeBase: null,
      routeProgress: null,
      routeScore: null,
      gaps: [],
      terrain: [],
      candidateZones: new Map(),
      feasibilityZones: new Map(),
      dataMarkers: new Map(),
      edges: new Map(),
      edgeRings: new Map(),
      drones: new Map(),
      droneFov: new Map(),
      convoy: new Map(),
      links: [],
      targets: new Map(),
      vectors: new Map(),
      vectorCorridors: new Map(),
      vectorMarkers: new Map(),
      detections: [],
      edgeSupport: [],
      searchCells: [],
      reroutes: [],
    },
    manualEdges: new Map(),
    approvedEdges: new Set(),
    rejectedEdges: new Set(),
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
    start: document.getElementById('startButton'),
    approveAll: document.getElementById('approveAllButton'),
    routeDistance: document.getElementById('routeDistance'),
    routeScore: document.getElementById('routeScore'),
    coveragePct: document.getElementById('coveragePct'),
    streamTime: document.getElementById('streamTime'),
    computeMode: document.getElementById('computeMode'),
    missionRoute: document.getElementById('missionRoute'),
    missionPhase: document.getElementById('missionPhase'),
    activeRisk: document.getElementById('activeRisk'),
    hudPhase: document.getElementById('hudPhase'),
    hudDrones: document.getElementById('hudDrones'),
    hudThreats: document.getElementById('hudThreats'),
    missionRibbon: document.getElementById('missionRibbon'),
    timelineStrip: document.getElementById('timelineStrip'),
    setupPanel: document.getElementById('setupPanel'),
    setupToggle: document.getElementById('setupToggle'),
    presentationToggle: document.getElementById('presentationToggle'),
    approvalCallout: document.getElementById('approvalCallout'),
    preflightSummary: document.getElementById('preflightSummary'),
    plannerList: document.getElementById('plannerList'),
    conditionList: document.getElementById('conditionList'),
    sourceList: document.getElementById('sourceList'),
    edgeList: document.getElementById('edgeList'),
    vectorList: document.getElementById('vectorList'),
    decisionList: document.getElementById('decisionList'),
    rerouteList: document.getElementById('rerouteList'),
    eventList: document.getElementById('eventList'),
    message: document.getElementById('message'),
    rerouteWarning: document.getElementById('rerouteWarning'),
    rerouteWarningText: document.getElementById('rerouteWarningText'),
  };

  function boot() {
    setPresentationMode(state.presentation);
    setSetupCollapsed(state.presentation);
    setActivePanel('planner');
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
      center: { lat: 50.4501, lng: 30.5234 },
      zoom: 13,
      mapTypeId: 'hybrid',
      tilt: 0,
      clickableIcons: false,
      fullscreenControl: false,
      streetViewControl: false,
      zoomControl: false,
      gestureHandling: 'greedy',
      backgroundColor: '#050708',
      styles: TACTICAL_MAP_STYLES,
      mapTypeControlOptions: {
        mapTypeIds: ['hybrid', 'satellite', 'terrain', 'roadmap'],
      },
    });
    state.info = new google.maps.InfoWindow();
    state.map.addListener('dragstart', function () { setCameraMode('free'); });
  }

  function bindEvents() {
    els.form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      cancelAutoReroute();
      state.manualEdges.clear();
      state.approvedEdges.clear();
      state.rejectedEdges.clear();
      analyze();
    });
    els.approveAll.addEventListener('click', approveAllEdges);
    els.start.addEventListener('click', startSimulation);
    if (els.setupToggle) {
      els.setupToggle.addEventListener('click', function () {
        setSetupCollapsed(!state.setupCollapsed);
      });
    }
    if (els.presentationToggle) {
      els.presentationToggle.addEventListener('click', function () {
        setPresentationMode(!state.presentation);
      });
    }
    document.querySelectorAll('[data-camera]').forEach(function (button) {
      button.addEventListener('click', function () {
        setCameraMode(button.getAttribute('data-camera'));
      });
    });
    document.querySelectorAll('[data-layer]').forEach(function (button) {
      button.addEventListener('click', function () {
        toggleLayer(button.getAttribute('data-layer'));
      });
    });
    document.querySelectorAll('[data-panel]').forEach(function (button) {
      button.addEventListener('click', function () {
        setActivePanel(button.getAttribute('data-panel'));
      });
    });
  }

  function analyze() {
    setBusy(true);
    hideError();
    cancelAutoReroute();
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
        state.rerouteRequested = false;
        syncApprovalState(scenario);
        renderScenario(scenario);
        setSetupCollapsed(true);
        setActivePanel('edges');
      })
      .catch(showError)
      .finally(function () { setBusy(false); });
  }

  function patchEdges() {
    if (!state.scenario) return Promise.resolve();
    setBusy(true);
    return fetch('/api/realworld/scenarios/' + state.scenario.scenario_id + '/edges', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        manual_edges: Array.from(state.manualEdges.values()),
        approved_edge_ids: Array.from(state.approvedEdges),
        rejected_edge_ids: Array.from(state.rejectedEdges),
      }),
    })
      .then(assertOk)
      .then(function (scenario) {
        state.scenario = scenario;
        syncApprovalState(scenario);
        renderScenario(scenario);
      })
      .catch(showError)
      .finally(function () { setBusy(false); });
  }

  function startSimulation() {
    if (!state.scenario) return;
    cancelAutoReroute();
    setBusy(true);
    fetch('/api/realworld/scenarios/' + state.scenario.scenario_id + '/start', { method: 'POST' })
      .then(assertOk)
      .then(function (scenario) {
        state.scenario = scenario;
        syncApprovalState(scenario);
        renderScenario(scenario);
        setCameraMode('follow');
        setSetupCollapsed(true);
        setActivePanel('decisions');
        openStream(scenario.scenario_id);
      })
      .catch(showError)
      .finally(function () { setBusy(false); });
  }

  function proposeReroutes() {
    if (!state.scenario || state.rerouteRequested) return;
    if (Date.now() < state.autoRerouteCooldownUntil) return;
    state.rerouteRequested = true;
    fetch('/api/realworld/scenarios/' + state.scenario.scenario_id + '/reroutes', { method: 'POST' })
      .then(assertOk)
      .then(function (scenario) {
        state.scenario = scenario;
        const proposals = scenario.analysis.reroute_proposals || [];
        renderReroutes(proposals);
        if (proposals.length) {
          setActivePanel('reroutes');
          scheduleAutoReroute(proposals[0]);
        }
        else {
          state.rerouteRequested = false;
          hideRerouteWarning();
        }
      })
      .catch(function (error) {
        state.rerouteRequested = false;
        showError(error);
      });
  }

  function applyReroute(proposalId, auto) {
    if (!state.scenario) return;
    cancelAutoReroute();
    setBusy(true);
    const wasStreaming = state.ws && state.ws.readyState === WebSocket.OPEN;
    fetch('/api/realworld/scenarios/' + state.scenario.scenario_id + '/reroutes/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proposal_id: proposalId }),
    })
      .then(assertOk)
      .then(function (scenario) {
        state.scenario = scenario;
        state.rerouteRequested = false;
        state.autoRerouteCooldownUntil = Date.now() + AUTO_REROUTE_COOLDOWN_MS;
        state.approvedEdges.clear();
        state.rejectedEdges.clear();
        state.manualEdges.clear();
        syncApprovalState(scenario);
        renderScenario(scenario, { preserveCamera: wasStreaming });
        setActivePanel('decisions');
        if (
          scenario.preflight &&
          scenario.preflight.started &&
          (!state.ws || state.ws.readyState === WebSocket.CLOSED)
        ) {
          openStream(scenario.scenario_id);
        }
      })
      .catch(function (error) {
        if (!auto) showError(error);
        else {
          state.rerouteRequested = false;
          showError(error);
        }
      })
      .finally(function () { setBusy(false); });
  }

  function scheduleAutoReroute(proposal) {
    cancelAutoReroute(false);
    showRerouteWarning(
      'Auto reroute in ' + (AUTO_REROUTE_DELAY_MS / 1000).toFixed(1) +
      's: ' + proposal.id + ', score ' + proposal.score.toFixed(1) + '. ' +
      rerouteSupportReason(proposal)
    );
    state.autoRerouteTimer = window.setTimeout(function () {
      state.autoRerouteTimer = null;
      applyReroute(proposal.id, true);
    }, AUTO_REROUTE_DELAY_MS);
  }

  function cancelAutoReroute(hide) {
    if (state.autoRerouteTimer) {
      window.clearTimeout(state.autoRerouteTimer);
      state.autoRerouteTimer = null;
    }
    if (hide !== false) hideRerouteWarning();
  }

  function showRerouteWarning(text) {
    if (!els.rerouteWarning) return;
    els.rerouteWarning.classList.add('show');
    els.rerouteWarningText.textContent = text;
  }

  function hideRerouteWarning() {
    if (!els.rerouteWarning) return;
    els.rerouteWarning.classList.remove('show');
  }

  function syncApprovalState(scenario) {
    state.approvedEdges.clear();
    state.rejectedEdges.clear();
    (scenario.analysis.edges || []).forEach(function (edge) {
      if (edge.status === 'approved' || edge.status === 'moved') state.approvedEdges.add(edge.id);
      if (edge.status === 'rejected') state.rejectedEdges.add(edge.id);
    });
  }

  function approveAllEdges() {
    if (!state.scenario) return;
    (state.scenario.analysis.edges || []).forEach(function (edge) {
      state.rejectedEdges.delete(edge.id);
      state.approvedEdges.add(edge.id);
    });
    patchEdges();
  }

  function renderScenario(scenario, options) {
    options = options || {};
    const route = scenario.route.points;
    const analysis = scenario.analysis;
    els.routeDistance.textContent = formatMeters(scenario.route.distance_m);
    els.coveragePct.textContent = analysis.coverage_percent.toFixed(1) + '%';
    if (els.routeScore) els.routeScore.textContent = routeScoreLabel(analysis.route_score);
    updateMissionFromScenario(scenario);
    renderPreflight(scenario);

    if (state.overlays.routeBase) state.overlays.routeBase.setMap(null);
    if (state.overlays.route) state.overlays.route.setMap(null);
    if (state.overlays.routeProgress) state.overlays.routeProgress.setMap(null);
    if (state.overlays.routeScore) state.overlays.routeScore.setMap(null);
    state.overlays.routeBase = new google.maps.Polyline({
      map: state.map,
      path: route,
      strokeColor: '#061012',
      strokeOpacity: 0.86,
      strokeWeight: 12,
    });
    state.overlays.route = new google.maps.Polyline({
      map: state.map,
      path: route,
      strokeColor: '#65e8ef',
      strokeOpacity: 0.95,
      strokeWeight: 4,
      icons: [{
        icon: { path: 'M 0,-1 0,1', strokeOpacity: .9, scale: 2 },
        offset: '0',
        repeat: '26px',
      }],
    });
    state.overlays.routeProgress = new google.maps.Polyline({
      map: state.map,
      path: [],
      strokeColor: '#4ae28a',
      strokeOpacity: 0.96,
      strokeWeight: 6,
    });
    state.overlays.routeScore = new google.maps.Polyline({
      map: state.layers.routeScore ? state.map : null,
      path: route,
      strokeColor: scoreColor((analysis.route_score && analysis.route_score.overall) || 0),
      strokeOpacity: 0.52,
      strokeWeight: 10,
      zIndex: 12,
    });

    state.overlays.gaps.forEach(function (gap) { gap.setMap(null); });
    state.overlays.gaps = analysis.coverage_gaps.map(function (gap) {
      return new google.maps.Polyline({
        map: state.map,
        path: [gap.start, gap.end],
        strokeColor: '#ff625d',
        strokeOpacity: 0.88,
        strokeWeight: 8,
        icons: [{
          icon: { path: 'M -2,0 2,0', strokeOpacity: 1, scale: 3 },
          offset: '0',
          repeat: '18px',
        }],
      });
    });

    if (!options.preserveCamera) {
      const bounds = new google.maps.LatLngBounds();
      route.forEach(function (p) { bounds.extend(p); });
      analysis.edges.forEach(function (edge) { bounds.extend({ lat: edge.lat, lng: edge.lng }); });
      state.map.fitBounds(bounds, 56);
    }

    renderEdges(analysis.edges, scenario.settings.wifi_radius_m);
    renderCandidateZones(analysis.candidate_zones || [], scenario.settings.wifi_radius_m);
    renderTerrainLayer((analysis.live_conditions && analysis.live_conditions.terrain) || null);
    renderDataAvailability(analysis);
    renderPlanning(scenario);
    renderConditions(analysis);
    renderEdgeList(analysis.edges);
    renderVectors(analysis.attack_vectors || []);
    renderReroutes(analysis.reroute_proposals || []);
  }

  function renderPreflight(scenario) {
    const p = scenario.preflight || {
      started: false,
      can_start: true,
      approved_stationary_edges: 0,
      min_required_stationary_edges: 0,
    };
    els.preflightSummary.textContent =
      p.approved_stationary_edges + '/' + p.min_required_stationary_edges +
      ' required stationary edges approved. Convoy-carried edge nodes activate after start.';
    if (els.approvalCallout) {
      els.approvalCallout.textContent = p.started ? 'running' : (p.can_start ? 'ready' : 'pending');
    }
    els.start.disabled = !p.can_start || p.started;
    els.start.textContent = p.started ? 'Running' : 'Start Simulation';
  }

  function renderPlanning(scenario) {
    if (!els.plannerList) return;
    const analysis = scenario.analysis || {};
    const score = analysis.route_score || {};
    const deploy = analysis.edge_deployability || {};
    const zones = analysis.candidate_zones || [];
    const approved = (analysis.edges || []).filter(function (edge) {
      return edge.status === 'approved' || edge.status === 'moved';
    }).length;
    const factors = score.factors || [];
    const narrative = decisionNarrative(score, deploy, zones, approved);
    els.plannerList.innerHTML =
      '<div class="card">' +
        '<div class="card-head"><span class="card-id">route score</span>' +
        '<span class="pill ' + scorePill(score.overall || 0) + '">' + routeScoreLabel(score) + '</span></div>' +
        '<div class="metric"><span>Grade</span><strong>' + esc(score.grade || 'pending') + '</strong></div>' +
        '<div class="metric"><span>Stationary Plan</span><strong>' + esc(deploy.summary || 'Candidate zones pending') + '</strong></div>' +
        '<div class="metric"><span>Approved Fixed</span><strong>' + approved + ' active / convoy edges after start</strong></div>' +
        '<div class="reason">' + esc(narrative) + '</div>' +
      '</div>' +
      factors.map(function (factor) {
        const pct = Math.round((factor.score || 0) * 100);
        return '<div class="card">' +
          '<div class="card-head"><span class="card-id">' + esc(factor.label) + '</span>' +
          '<span class="pill ' + scorePill(pct) + '">' + pct + '%</span></div>' +
          '<div class="metric"><span>Source</span><strong>' + esc(factor.status || 'derived') + '</strong></div>' +
          '<div class="reason">' + esc(factor.detail || '') + '</div>' +
          '<div class="factor-bar"><span style="width:' + Math.max(2, pct) + '%"></span></div>' +
        '</div>';
      }).join('');
  }

  function renderConditions(analysis) {
    if (!els.conditionList || !els.sourceList) return;
    const live = analysis.live_conditions || {};
    const terrain = live.terrain || {};
    const weather = live.weather || {};
    const traffic = live.traffic || {};
    const roads = live.road_context || {};
    els.conditionList.innerHTML =
      conditionCard('weather', weather.available ? weather.summary : 'Weather unavailable', [
        ['Temp', weather.temperature_c == null ? '--' : weather.temperature_c.toFixed(1) + ' C'],
        ['Wind', weather.wind_speed_kmh == null ? '--' : weather.wind_speed_kmh.toFixed(0) + ' km/h'],
        ['Precip', weather.precipitation_mm == null ? '--' : weather.precipitation_mm.toFixed(1) + ' mm'],
      ]) +
      conditionCard('traffic', traffic.summary || 'Traffic unavailable', [
        ['Delay', traffic.delay_ratio == null ? '--' : Math.round(traffic.delay_ratio * 100) + '%'],
        ['Intervals', String(traffic.speed_interval_count || 0)],
      ]) +
      conditionCard('terrain', 'Slope and elevation derived from Google Elevation', [
        ['Max slope', terrain.max_slope_pct == null ? '--' : terrain.max_slope_pct.toFixed(1) + '%'],
        ['Avg slope', terrain.avg_slope_pct == null ? '--' : terrain.avg_slope_pct.toFixed(1) + '%'],
        ['Gain', terrain.elevation_gain_m == null ? '--' : formatMeters(terrain.elevation_gain_m)],
      ]) +
      conditionCard('road context', roads.summary || 'Open map context unavailable', [
        ['Intersections', String(roads.intersection_count || 0)],
        ['Deployable hints', String(roads.deployable_hint_count || 0)],
      ]);

    els.sourceList.innerHTML = (analysis.data_sources || []).map(function (source) {
      return '<div class="card">' +
        '<div class="card-head"><span class="card-id">' + esc(source.label || source.key) + '</span>' +
        '<span class="source-state ' + esc(source.state || 'unavailable') + '">' + esc(source.state || 'unavailable') + '</span></div>' +
        '<div class="reason">' + esc(source.summary || '') + '</div>' +
      '</div>';
    }).join('');
  }

  function conditionCard(title, summary, metrics) {
    return '<div class="card">' +
      '<div class="card-head"><span class="card-id">' + esc(title) + '</span></div>' +
      metrics.map(function (item) {
        return '<div class="metric"><span>' + esc(item[0]) + '</span><strong>' + esc(item[1]) + '</strong></div>';
      }).join('') +
      '<div class="reason">' + esc(summary || '') + '</div>' +
    '</div>';
  }

  function renderCandidateZones(zones, radius) {
    const seen = new Set();
    zones.forEach(function (zone) {
      seen.add(zone.id);
      const pos = { lat: zone.lat, lng: zone.lng };
      const color = zoneColor(zone);
      let marker = state.overlays.candidateZones.get(zone.id);
      if (!marker) {
        marker = new google.maps.Circle({ clickable: true, strokeWeight: 1 });
        marker.addListener('click', function () { showZoneInfo(marker.__zone || zone, marker); });
        state.overlays.candidateZones.set(zone.id, marker);
      }
      marker.__zone = zone;
      marker.setOptions({
        map: state.layers.candidates ? state.map : null,
        center: pos,
        radius: Math.max(48, Math.min(radius * 0.72, 120)),
        strokeColor: color,
        strokeOpacity: zone.status === 'rejected' ? 0.38 : 0.74,
        fillColor: color,
        fillOpacity: zone.status === 'rejected' ? 0.035 : 0.075,
      });

      let heat = state.overlays.feasibilityZones.get(zone.id);
      if (!heat) {
        heat = new google.maps.Circle({ clickable: false, strokeWeight: 0 });
        state.overlays.feasibilityZones.set(zone.id, heat);
      }
      heat.setOptions({
        map: state.layers.feasibility ? state.map : null,
        center: pos,
        radius: Math.max(90, Math.min(radius * 1.3, 230)),
        fillColor: color,
        fillOpacity: Math.max(0.025, Math.min(0.16, (zone.feasibility_score || 0.4) * 0.14)),
        strokeOpacity: 0,
      });
    });
    deleteMissing(state.overlays.candidateZones, seen);
    deleteMissing(state.overlays.feasibilityZones, seen);
  }

  function renderTerrainLayer(terrain) {
    clearOverlayArray('terrain');
    if (!state.layers.terrain || !terrain || !terrain.segments) return;
    terrain.segments.forEach(function (segment) {
      state.overlays.terrain.push(new google.maps.Polyline({
        map: state.map,
        path: [segment.start, segment.end],
        strokeColor: terrainColor(segment.severity),
        strokeOpacity: segment.severity === 'low' ? 0.28 : 0.72,
        strokeWeight: segment.severity === 'steep' ? 7 : 4,
        zIndex: 14,
      }));
    });
  }

  function renderDataAvailability(analysis) {
    const sources = analysis.data_sources || [];
    const seen = new Set();
    if (!state.scenario || !state.scenario.route || !state.scenario.route.samples) return;
    const samples = state.scenario.route.samples;
    sources.forEach(function (source, idx) {
      const sample = samples[Math.min(samples.length - 1, Math.floor((idx + 1) / (sources.length + 1) * samples.length))];
      if (!sample) return;
      seen.add(source.key);
      let marker = state.overlays.dataMarkers.get(source.key);
      if (!marker) {
        marker = new google.maps.Marker({ clickable: true, zIndex: 74 });
        marker.addListener('click', function () {
          state.info.setContent('<div class="info"><strong>' + esc(source.label || source.key) + '</strong><br>' + esc(source.state || '') + '<br>' + esc(source.summary || '') + '</div>');
          state.info.open({ map: state.map, anchor: marker });
        });
        state.overlays.dataMarkers.set(source.key, marker);
      }
      marker.setOptions({
        map: state.layers.data ? state.map : null,
        position: sample,
        label: { text: String(idx + 1), color: '#061012', fontSize: '10px', fontWeight: '900' },
        icon: dataSourceIcon(source.state),
        title: source.label || source.key,
      });
    });
    deleteMissing(state.overlays.dataMarkers, seen);
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
          draggable: edge.status !== 'rejected',
          title: edge.id,
          icon: edgeIcon(edge.status, edge.edge_type),
          zIndex: 80,
        });
        marker.addListener('click', function () { showEdgeInfo(edge, marker); });
        marker.addListener('dragend', function () {
          const p = marker.getPosition();
          state.manualEdges.set(edge.id, { id: edge.id, lat: p.lat(), lng: p.lng() });
          state.approvedEdges.add(edge.id);
          state.rejectedEdges.delete(edge.id);
          patchEdges();
        });
        state.overlays.edges.set(edge.id, marker);
      }
      marker.setPosition(pos);
      marker.setDraggable(edge.status !== 'rejected');
      marker.setIcon(edgeIcon(edge.status, edge.edge_type));

      let ring = state.overlays.edgeRings.get(edge.id);
      if (!ring) {
        ring = new google.maps.Circle({
          map: state.map,
          strokeWeight: 1,
          clickable: false,
        });
        state.overlays.edgeRings.set(edge.id, ring);
      }
      const col = edgeColor(edge.status, edge.edge_type);
      ring.setOptions({
        strokeColor: col,
        strokeOpacity: edge.status === 'rejected' ? 0.14 : 0.34,
        fillColor: col,
        fillOpacity: edge.status === 'approved' || edge.status === 'moved' ? 0.055 : 0.025,
      });
      ring.setCenter(pos);
      ring.setRadius(radius);
    });

    state.overlays.edges.forEach(function (_marker, id) {
      if (String(id).indexOf('convoy_edge_') === 0) nextIds.add(id);
    });
    deleteMissing(state.overlays.edges, nextIds);
    deleteMissing(state.overlays.edgeRings, nextIds);
  }

  function openStream(scenarioId) {
    closeStream();
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
    resetLiveMotionOnRouteRevision(frame);
    updateMissionFromFrame(frame);
    updateRouteProgress(frame);
    renderLiveEdges(frame.edges || [], state.scenario.settings.wifi_radius_m);
    renderActors(frame);
    renderLinks(frame);
    renderTargets(frame);
    renderVectors((frame.geo && frame.geo.attack_vectors) || []);
    renderDetections(frame);
    renderEdgeSupport(frame);
    renderDecisions(frame);
    renderEvents(frame.events || []);
    renderTimeline(frame, frame.events || []);
    if (frame.reroute && frame.reroute.recommended) proposeReroutes();
    followCamera(frame);
  }

  function renderLiveEdges(edges, radius) {
    edges.forEach(function (edge) {
      if (state.overlays.edges.has(edge.id) && edge.edge_type !== 'convoy_edge') return;
      const pos = edge.geo;
      let marker = state.overlays.edges.get(edge.id);
      if (!marker) {
        marker = new google.maps.Marker({
          map: state.map,
          position: pos,
          draggable: false,
          title: edge.id,
          icon: edgeIcon(edge.status, edge.edge_type),
          zIndex: edge.edge_type === 'convoy_edge' ? 92 : 82,
        });
        state.overlays.edges.set(edge.id, marker);
      }
      smoothOverlayPosition(marker, pos, 'setPosition', 'getPosition', MOTION_SMOOTH_MS);
      marker.setIcon(edgeIcon(edge.status, edge.edge_type));
      let ring = state.overlays.edgeRings.get(edge.id);
      if (!ring) {
        ring = new google.maps.Circle({ map: state.map, clickable: false, strokeWeight: 1 });
        state.overlays.edgeRings.set(edge.id, ring);
      }
      const col = edgeColor(edge.status, edge.edge_type);
      ring.setOptions({ strokeColor: col, fillColor: col, strokeOpacity: 0.28, fillOpacity: 0.04 });
      smoothOverlayPosition(ring, pos, 'setCenter', 'getCenter', MOTION_SMOOTH_MS);
      ring.setRadius(radius);
    });
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
        fov = new google.maps.Circle({ map: state.map, strokeWeight: 1, clickable: false });
        state.overlays.droneFov.set(drone.id, fov);
      }
      const col = drone.tier === 'PARENT' ? '#6cb7ff' : taskColor(drone.current_task);
      fov.setOptions({
        strokeColor: col,
        strokeOpacity: drone.tier === 'PARENT' ? 0.42 : 0.27,
        fillColor: col,
        fillOpacity: drone.tier === 'PARENT' ? 0.038 : 0.022,
        strokeWeight: drone.tier === 'PARENT' ? 2 : 1,
      });
      smoothOverlayPosition(fov, drone.geo, 'setCenter', 'getCenter', MOTION_SMOOTH_MS);
      fov.setRadius(drone.capabilities.vision_radius_m);
    });
    deleteMissing(state.overlays.drones, droneIds);
    deleteMissing(state.overlays.droneFov, droneIds);
  }

  function renderLinks(frame) {
    state.overlays.links.forEach(function (link) { link.setMap(null); });
    state.overlays.links = [];
    if (!state.layers.links) return;
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

  function renderVectors(vectors) {
    const ids = new Set();
    if (!state.layers.vectors) {
      state.overlays.vectors.forEach(function (line) { line.setMap(null); });
      state.overlays.vectors.clear();
      state.overlays.vectorCorridors.forEach(function (corridor) { corridor.setMap(null); });
      state.overlays.vectorCorridors.clear();
      state.overlays.vectorMarkers.forEach(function (marker) { marker.setMap(null); });
      state.overlays.vectorMarkers.clear();
      renderVectorList(vectors);
      return;
    }
    vectors.forEach(function (vector, idx) {
      if (!vector.start || !vector.end) return;
      ids.add(vector.id);
      const corridorColor = vector.type === 'synthetic_gap_pressure' ? '#efbf55' : '#ff625d';
      let corridor = state.overlays.vectorCorridors.get(vector.id);
      if (!corridor) {
        corridor = new google.maps.Polygon({
          map: state.map,
          clickable: false,
          strokeColor: corridorColor,
          strokeOpacity: 0.22,
          strokeWeight: 1,
          fillColor: corridorColor,
          fillOpacity: Math.max(0.06, Math.min(0.18, (vector.risk || 0.35) * 0.18)),
          zIndex: 34,
        });
        state.overlays.vectorCorridors.set(vector.id, corridor);
      }
      corridor.setOptions({
        map: state.map,
        strokeColor: corridorColor,
        fillColor: corridorColor,
        fillOpacity: Math.max(0.06, Math.min(0.18, (vector.risk || 0.35) * 0.18)),
        zIndex: 34,
      });
      corridor.setPath(corridorPath(vector.start, vector.end, vector.width_m || 160));
      let line = state.overlays.vectors.get(vector.id);
      if (!line) {
        line = new google.maps.Polyline({
          map: state.map,
          strokeColor: corridorColor,
          strokeOpacity: 0.76,
          strokeWeight: Math.max(3, Math.min(8, (vector.width_m || 160) / 45)),
          zIndex: 86,
          icons: [{
            icon: { path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW, scale: 3.4, strokeColor: corridorColor },
            offset: '72%',
            repeat: '86px',
          }],
        });
        state.overlays.vectors.set(vector.id, line);
      }
      line.setOptions({
        map: state.map,
        strokeColor: corridorColor,
        strokeOpacity: vector.type === 'synthetic_gap_pressure' ? 0.78 : 0.9,
        strokeWeight: Math.max(4, Math.min(9, (vector.width_m || 160) / 38)),
        zIndex: 86,
        icons: [{
          icon: { path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW, scale: 3.4, strokeColor: corridorColor },
          offset: '72%',
          repeat: '86px',
        }],
      });
      line.setPath([vector.start, vector.end]);

      let marker = state.overlays.vectorMarkers.get(vector.id);
      if (!marker) {
        marker = new google.maps.Marker({
          clickable: true,
          zIndex: 112,
        });
        marker.addListener('click', function () { showVectorInfo(marker.__vector || vector, marker); });
        state.overlays.vectorMarkers.set(vector.id, marker);
      }
      marker.__vector = vector;
      marker.setOptions({
        map: state.map,
        position: vector.end,
        icon: vectorIcon(vector),
        label: { text: 'V' + (idx + 1), color: '#ffffff', fontSize: '10px', fontWeight: '900' },
        title: vector.id,
      });
    });
    deleteMissing(state.overlays.vectors, ids);
    deleteMissing(state.overlays.vectorCorridors, ids);
    deleteMissing(state.overlays.vectorMarkers, ids);
    renderVectorList(vectors);
  }

  function renderDetections(frame) {
    state.overlays.detections.forEach(function (line) { line.setMap(null); });
    state.overlays.detections = [];
    if (!state.layers.detections) return;
    const actors = {};
    (frame.drones || []).forEach(function (actor) { actors[actor.id] = actor.geo; });
    const targets = {};
    ((frame.sensing && frame.sensing.targets) || []).forEach(function (target) {
      targets[target.id] = { lat: target.lat, lng: target.lng };
    });
    ((frame.sensing && frame.sensing.detections) || []).slice(-24).forEach(function (det) {
      const a = actors[det.observer_id];
      const b = targets[det.target_id];
      if (!a || !b) return;
      state.overlays.detections.push(new google.maps.Polyline({
        map: state.map,
        path: [a, b],
        strokeColor: det.observer_tier === 'PARENT' ? '#6cb7ff' : '#eef5ec',
        strokeOpacity: 0.24 + det.confidence * 0.44,
        strokeWeight: 1,
      }));
    });
  }

  function renderEdgeSupport(frame) {
    state.overlays.edgeSupport.forEach(function (line) { line.setMap(null); });
    state.overlays.edgeSupport = [];
    state.overlays.searchCells.forEach(function (circle) { circle.setMap(null); });
    state.overlays.searchCells = [];

    const edges = {};
    (frame.edges || []).forEach(function (edge) { edges[edge.id] = edge.geo; });
    (frame.drones || []).forEach(function (drone) {
      const anchorId = drone.connected_edge_id || drone.edge_anchor_id;
      const anchor = anchorId && edges[anchorId];
      if (drone.tier === 'PARENT' && anchor) {
        state.overlays.edgeSupport.push(new google.maps.Polyline({
          map: state.map,
          path: [drone.geo, anchor],
          strokeColor: drone.edge_connected ? '#45d483' : '#efbf55',
          strokeOpacity: drone.edge_connected ? 0.72 : 0.36,
          strokeWeight: drone.edge_connected ? 3 : 2,
          icons: [{ icon: { path: 'M 0,-1 0,1', strokeOpacity: 1, scale: 2 }, offset: '0', repeat: '12px' }],
        }));
      }
      const activeSearch = state.layers.search && (
        String(drone.assignment || '').indexOf('investigate_') === 0 ||
        String(drone.assignment || '').indexOf('screen_') === 0 ||
        String(drone.assignment || '').indexOf('edge_assisted') >= 0
      );
      if (activeSearch) {
        const parent = drone.tier === 'PARENT';
        state.overlays.searchCells.push(new google.maps.Circle({
          map: state.map,
          center: drone.geo,
          radius: parent ? 92 : 48,
          clickable: false,
          strokeColor: drone.edge_connected || drone.edge_supported ? '#45d483' : taskColor(drone.current_task),
          strokeOpacity: parent ? 0.5 : 0.34,
          strokeWeight: parent ? 2 : 1,
          fillColor: drone.edge_connected || drone.edge_supported ? '#45d483' : taskColor(drone.current_task),
          fillOpacity: parent ? 0.045 : 0.035,
        }));
      }
    });
  }

  function renderDecisions(frame) {
    const sensing = frame.sensing || {};
    const tracks = sensing.fused_tracks || [];
    const parents = (frame.drones || []).filter(function (d) { return d.tier === 'PARENT'; });
    const smalls = (frame.drones || []).filter(function (d) { return d.tier === 'SMALL'; });
    els.computeMode.textContent = parents.length
      ? parents.map(function (p) { return p.compute_mode === 'edge_augmented' ? 'edge' : 'local'; }).join('/')
      : '--';
    els.decisionList.innerHTML = '';

    const lead = (frame.convoy || [])[0];
    if (lead && lead.route_adaptation) {
      const liveReroute = frame.reroute && frame.reroute.applied;
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-head"><span class="card-id">convoy route control</span>' +
        '<span class="pill ' + (lead.route_adaptation.mode === 'nominal_route_follow' ? 'edge' : 'warn') + '">' +
        esc(lead.route_adaptation.mode) + '</span></div>' +
        '<div class="metric"><span>Speed</span><strong>' + lead.speed_mps.toFixed(1) + ' m/s</strong></div>' +
        '<div class="metric"><span>Offset</span><strong>' + lead.route_adaptation.lateral_offset_m.toFixed(1) + ' m</strong></div>' +
        (liveReroute ? '<div class="metric"><span>Route</span><strong>rev ' + liveReroute.route_revision + ' live</strong></div>' : '') +
        '<div class="reason">' + esc(lead.route_adaptation.reason || 'Route following nominal.') + '</div>';
      els.decisionList.appendChild(card);
    }

    parents.forEach(function (parent) {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-head"><span class="card-id">' + esc(parent.id) + '</span>' +
        '<span class="pill ' + (parent.compute_mode === 'edge_augmented' ? 'edge' : 'warn') + '">' +
        esc(parent.compute_mode) + '</span></div>' +
        '<div class="metric"><span>Sector</span><strong>' + esc(parent.sector_id) + '</strong></div>' +
        '<div class="metric"><span>Assignment</span><strong>' + esc(parent.assignment || parent.current_task) + '</strong></div>' +
        '<div class="metric"><span>Edge</span><strong>' + esc(edgeAnchorLabel(parent)) + '</strong></div>' +
        '<div class="metric"><span>Mode</span><strong>' + esc(parent.edge_connectivity_mode || 'none') + '</strong></div>' +
        '<div class="metric"><span>Search</span><strong>' + esc(searchCellLabel(parent.search_cell)) + '</strong></div>' +
        '<div class="metric"><span>Controls</span><strong>' + esc((parent.controls || []).join(', ')) + '</strong></div>' +
        '<div class="metric"><span>FoV</span><strong>' + parent.capabilities.vision_radius_m.toFixed(0) + ' m</strong></div>' +
        '<div class="metric"><span>Functions</span><strong>' + esc(parent.available_functions.join(', ')) + '</strong></div>';
      els.decisionList.appendChild(card);
    });

    smalls
      .filter(function (small) { return String(small.assignment || '').indexOf('investigate_') === 0 || String(small.assignment || '').indexOf('screen_') === 0; })
      .slice(0, 8)
      .forEach(function (small) {
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML =
          '<div class="card-head"><span class="card-id">' + esc(small.id) + '</span>' +
          '<span class="pill track">' + esc(small.assignment) + '</span></div>' +
          '<div class="metric"><span>Parent</span><strong>' + esc(small.controlled_by || '--') + '</strong></div>' +
          '<div class="metric"><span>Edge</span><strong>' + esc(edgeAnchorLabel(small)) + '</strong></div>' +
          '<div class="metric"><span>Sector</span><strong>' + esc(small.sector_id) + '</strong></div>' +
          '<div class="metric"><span>Search</span><strong>' + esc(searchCellLabel(small.search_cell)) + '</strong></div>';
        els.decisionList.appendChild(card);
      });

    tracks.forEach(function (track) {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-head"><span class="card-id">' + esc(track.target_id) + '</span>' +
        '<span class="pill track">' + esc(track.status) + '</span></div>' +
        '<div class="metric"><span>Vector</span><strong>' + esc(track.attack_vector_id || '--') + '</strong></div>' +
        '<div class="metric"><span>Fusion</span><strong>' + esc(track.fusion_parent_id) + '</strong></div>' +
        '<div class="metric"><span>Edge</span><strong>' + esc(track.edge_assisted ? (track.edge_anchor_id || 'assisted') : 'local') + '</strong></div>' +
        '<div class="metric"><span>Quality</span><strong>' + esc(track.classification_quality || '--') + '</strong></div>' +
        '<div class="metric"><span>Reports</span><strong>' + track.report_count + ' / ' + Math.round(track.confidence * 100) + '%</strong></div>' +
        '<div class="reason">' + esc(track.fusion_confidence_reason || '') + '</div>';
      els.decisionList.appendChild(card);
    });
  }

  function renderEdgeList(edges) {
    els.edgeList.innerHTML = '';
    edges.forEach(function (edge) {
      const card = document.createElement('div');
      card.className = 'card edge-card ' + edge.status;
      card.innerHTML =
        '<div class="card-head"><span class="card-id">' + esc(edge.id) + '</span>' +
        '<span class="pill ' + statusClass(edge.status) + '">' + esc(edge.status.toUpperCase()) + '</span></div>' +
        '<div class="metric"><span>Coverage</span><strong>' + formatMeters(edge.coverage_m) + ' / ' + edge.covered_route_percent + '%</strong></div>' +
        '<div class="metric"><span>Location</span><strong>' + edge.lat.toFixed(5) + ', ' + edge.lng.toFixed(5) + '</strong></div>' +
        '<div class="metric"><span>Latency</span><strong>' + edge.avg_latency_ms.toFixed(1) + ' ms</strong></div>' +
        '<div class="metric"><span>Access</span><strong>' + (edge.nearest_road_distance_m == null ? 'unverified' : edge.nearest_road_distance_m.toFixed(0) + ' m') + '</strong></div>' +
        '<div class="metric"><span>Feasibility</span><strong>' + Math.round((edge.feasibility_score || 0) * 100) + '% / ' + esc(edge.deployability_class || 'medium') + '</strong></div>' +
        '<div class="metric"><span>Elevation</span><strong>' + edge.elevation_advantage_m.toFixed(1) + ' m</strong></div>' +
        '<div class="metric"><span>Redundancy</span><strong>' + Math.round(edge.redundancy_contribution * 100) + '%</strong></div>' +
        '<div class="reason">' + esc((edge.constraints || []).join(', ') || edge.reasons[0] || '') + '</div>' +
        '<div class="button-row mini">' +
          '<button type="button" data-edge-action="approve" data-edge-id="' + esc(edge.id) + '">Approve</button>' +
          '<button type="button" data-edge-action="reject" data-edge-id="' + esc(edge.id) + '" class="danger">Reject</button>' +
        '</div>';
      els.edgeList.appendChild(card);
    });
    els.edgeList.querySelectorAll('[data-edge-action]').forEach(function (button) {
      button.addEventListener('click', function () {
        const id = button.getAttribute('data-edge-id');
        const action = button.getAttribute('data-edge-action');
        if (action === 'approve') {
          state.approvedEdges.add(id);
          state.rejectedEdges.delete(id);
        } else {
          state.approvedEdges.delete(id);
          state.rejectedEdges.add(id);
        }
        patchEdges();
      });
    });
  }

  function renderVectorList(vectors) {
    els.vectorList.innerHTML = '';
    if (!vectors.length) {
      els.vectorList.innerHTML = '<div class="summary">No synthetic scenario vectors are active.</div>';
      return;
    }
    vectors.forEach(function (vector) {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-head"><span class="card-id">' + esc(vector.id) + '</span>' +
        '<span class="pill warn">' + Math.round((vector.risk || 0) * 100) + '% synthetic</span></div>' +
        '<div class="metric"><span>Type</span><strong>' + esc(vector.type) + '</strong></div>' +
        '<div class="metric"><span>Width</span><strong>' + formatMeters(vector.width_m || 0) + '</strong></div>' +
        '<div class="metric"><span>Route Ref</span><strong>' + formatMeters(vector.route_distance_m || 0) + '</strong></div>' +
        '<div class="reason">' + esc(vector.explanation || 'Synthetic scenario object; not live intelligence.') + '</div>';
      els.vectorList.appendChild(card);
    });
  }

  function renderReroutes(proposals) {
    state.overlays.reroutes.forEach(function (line) { line.setMap(null); });
    state.overlays.reroutes = [];
    els.rerouteList.innerHTML = '';
    if (!proposals.length) {
      els.rerouteList.innerHTML = '<div class="summary">No auto reroute pending.</div>';
      return;
    }
    proposals.forEach(function (proposal, idx) {
      state.overlays.reroutes.push(new google.maps.Polyline({
        map: state.map,
        path: proposal.points,
        strokeColor: idx === 0 ? '#45d483' : '#6cb7ff',
        strokeOpacity: idx === 0 ? 0.78 : 0.44,
        strokeWeight: idx === 0 ? 5 : 3,
        icons: [{
          icon: { path: 'M 0,-1 0,1', strokeOpacity: 1, scale: 3 },
          offset: '0',
          repeat: idx === 0 ? '20px' : '28px',
        }],
      }));
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-head"><span class="card-id">' + esc(proposal.id) + '</span>' +
        '<span class="pill edge">' + proposal.score.toFixed(1) + '</span></div>' +
        '<div class="metric"><span>Distance</span><strong>' + formatMeters(proposal.distance_m) + '</strong></div>' +
        '<div class="metric"><span>Risk</span><strong>' + Math.round(proposal.risk_score * 100) + '%</strong></div>' +
        '<div class="metric"><span>Edge</span><strong>' + Math.round((proposal.edge_coverage_score || 0) * 100) + '%</strong></div>' +
        '<div class="metric"><span>Connect</span><strong>' + Math.round((proposal.connectivity_score || 0) * 100) + '%</strong></div>' +
        '<div class="metric"><span>Terrain</span><strong>' + factorPercent(proposal.route_score, 'terrain_slope') + '</strong></div>' +
        '<div class="metric"><span>Weather</span><strong>' + factorPercent(proposal.route_score, 'weather_visibility') + '</strong></div>' +
        '<div class="reason">' + esc((proposal.reasons || [])[0] || '') + '</div>' +
        '<div class="button-row mini"><button type="button" data-reroute-id="' + esc(proposal.id) + '">Apply Now</button></div>';
      els.rerouteList.appendChild(card);
    });
    els.rerouteList.querySelectorAll('[data-reroute-id]').forEach(function (button) {
      button.addEventListener('click', function () {
        applyReroute(button.getAttribute('data-reroute-id'), false);
      });
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

  function resetLiveMotionOnRouteRevision(frame) {
    const revision = frame.geo && frame.geo.route_revision;
    if (revision == null) return;
    if (state.lastRouteRevision === null) {
      state.lastRouteRevision = revision;
      return;
    }
    if (revision === state.lastRouteRevision) return;
    state.lastRouteRevision = revision;
    clearMarkerStore(state.overlays.drones);
    clearMarkerStore(state.overlays.droneFov);
    clearMarkerStore(state.overlays.convoy);
    clearMatchingOverlays(state.overlays.edges, function (id) { return String(id).indexOf('convoy_edge_') === 0; });
    clearMatchingOverlays(state.overlays.edgeRings, function (id) { return String(id).indexOf('convoy_edge_') === 0; });
  }

  function clearMarkerStore(store) {
    store.forEach(function (overlay) {
      if (overlay.__motionFrame) window.cancelAnimationFrame(overlay.__motionFrame);
      overlay.setMap(null);
    });
    store.clear();
  }

  function clearMatchingOverlays(store, predicate) {
    Array.from(store.keys()).forEach(function (id) {
      if (!predicate(id)) return;
      const overlay = store.get(id);
      if (overlay.__motionFrame) window.cancelAnimationFrame(overlay.__motionFrame);
      overlay.setMap(null);
      store.delete(id);
    });
  }

  function upsertMarker(store, id, position, icon, zIndex) {
    let marker = store.get(id);
    if (!marker) {
      marker = new google.maps.Marker({ map: state.map, position: position, icon: icon, title: id, zIndex: zIndex });
      marker.__motionPoint = plainLatLng(position);
      store.set(id, marker);
    }
    smoothOverlayPosition(marker, position, 'setPosition', 'getPosition', MOTION_SMOOTH_MS);
    marker.setIcon(icon);
    return marker;
  }

  function deleteMissing(store, nextIds) {
    Array.from(store.keys()).forEach(function (id) {
      if (!nextIds.has(id)) {
        const overlay = store.get(id);
        if (overlay.__motionFrame) window.cancelAnimationFrame(overlay.__motionFrame);
        overlay.setMap(null);
        store.delete(id);
      }
    });
  }

  function clearScenario() {
    hideRerouteWarning();
    state.lastRouteRevision = null;
    if (state.overlays.routeBase) state.overlays.routeBase.setMap(null);
    if (state.overlays.route) state.overlays.route.setMap(null);
    if (state.overlays.routeProgress) state.overlays.routeProgress.setMap(null);
    if (state.overlays.routeScore) state.overlays.routeScore.setMap(null);
    state.overlays.routeBase = null;
    state.overlays.route = null;
    state.overlays.routeProgress = null;
    state.overlays.routeScore = null;
    state.overlays.gaps.forEach(function (gap) { gap.setMap(null); });
    state.overlays.gaps = [];
    ['edges', 'edgeRings', 'drones', 'droneFov', 'convoy', 'targets', 'vectors', 'vectorCorridors', 'vectorMarkers', 'candidateZones', 'feasibilityZones', 'dataMarkers'].forEach(function (key) {
      state.overlays[key].forEach(function (overlay) { overlay.setMap(null); });
      state.overlays[key].clear();
    });
    ['links', 'detections', 'edgeSupport', 'searchCells', 'reroutes', 'terrain'].forEach(function (key) {
      state.overlays[key].forEach(function (overlay) { overlay.setMap(null); });
      state.overlays[key] = [];
    });
    if (els.plannerList) els.plannerList.innerHTML = '';
    if (els.conditionList) els.conditionList.innerHTML = '';
    if (els.sourceList) els.sourceList.innerHTML = '';
    els.edgeList.innerHTML = '';
    els.vectorList.innerHTML = '';
    els.decisionList.innerHTML = '';
    els.rerouteList.innerHTML = '';
    els.eventList.innerHTML = '';
    if (els.timelineStrip) els.timelineStrip.innerHTML = '<span class="timeline-empty">Awaiting live telemetry.</span>';
  }

  function showEdgeInfo(edge, marker) {
    const html =
      '<div class="info"><strong>' + esc(edge.id) + '</strong><br>' +
      'Status: ' + esc(edge.status) + '<br>' +
      'Feasibility: ' + Math.round((edge.feasibility_score || 0) * 100) + '% ' + esc(edge.deployability_class || '') + '<br>' +
      edge.reasons.map(esc).join('<br>') + '</div>';
    state.info.setContent(html);
    state.info.open({ map: state.map, anchor: marker });
  }

  function showZoneInfo(zone, overlay) {
    const html =
      '<div class="info"><strong>' + esc(zone.id) + '</strong><br>' +
      'Status: ' + esc(zone.status || 'candidate') + '<br>' +
      'Deployability: ' + Math.round((zone.feasibility_score || 0) * 100) + '% ' + esc(zone.deployability_class || '') + '<br>' +
      'Access: ' + (zone.nearest_road_distance_m == null ? 'unverified' : Math.round(zone.nearest_road_distance_m) + ' m') + '<br>' +
      esc((zone.constraints || []).join(', ')) + '</div>';
    state.info.setContent(html);
    state.info.setPosition(overlay.getCenter());
    state.info.open({ map: state.map });
  }

  function showVectorInfo(vector, marker) {
    const html =
      '<div class="info"><strong>' + esc(vector.id) + '</strong><br>' +
      'Type: ' + esc(vector.type || 'synthetic_vector') + '<br>' +
      'Synthetic risk: ' + Math.round((vector.risk || 0) * 100) + '%<br>' +
      'Width: ' + formatMeters(vector.width_m || 0) + '<br>' +
      esc(vector.explanation || 'Synthetic scenario object; not live intelligence.') + '</div>';
    state.info.setContent(html);
    state.info.open({ map: state.map, anchor: marker });
  }

  function setSetupCollapsed(collapsed) {
    state.setupCollapsed = Boolean(collapsed);
    document.body.classList.toggle('setup-collapsed', state.setupCollapsed);
    if (els.setupToggle) els.setupToggle.textContent = state.setupCollapsed ? 'Setup' : 'Hide Setup';
  }

  function setPresentationMode(enabled) {
    state.presentation = Boolean(enabled);
    document.body.classList.toggle('presentation', state.presentation);
    if (els.presentationToggle) {
      els.presentationToggle.textContent = state.presentation ? 'Exit Presentation' : 'Defense Presentation';
    }
    if (state.presentation) {
      setSetupCollapsed(true);
      setActivePanel('planner');
    }
  }

  function setActivePanel(panel) {
    state.activePanel = panel || 'edges';
    document.querySelectorAll('[data-panel]').forEach(function (button) {
      button.classList.toggle('active', button.getAttribute('data-panel') === state.activePanel);
    });
    document.querySelectorAll('[data-panel-content]').forEach(function (section) {
      section.classList.toggle('active', section.getAttribute('data-panel-content') === state.activePanel);
    });
  }

  function toggleLayer(layer) {
    if (!Object.prototype.hasOwnProperty.call(state.layers, layer)) return;
    state.layers[layer] = !state.layers[layer];
    document.querySelectorAll('[data-layer="' + layer + '"]').forEach(function (button) {
      button.classList.toggle('active', state.layers[layer]);
    });
    if (!state.scenario) return;
    if (layer === 'vectors') renderVectors(state.scenario.analysis.attack_vectors || []);
    if (layer === 'routeScore' && state.overlays.routeScore) {
      state.overlays.routeScore.setMap(state.layers.routeScore ? state.map : null);
    }
    if (layer === 'terrain') renderTerrainLayer((state.scenario.analysis.live_conditions && state.scenario.analysis.live_conditions.terrain) || null);
    if (layer === 'candidates' || layer === 'feasibility') {
      renderCandidateZones(state.scenario.analysis.candidate_zones || [], state.scenario.settings.wifi_radius_m);
    }
    if (layer === 'data') renderDataAvailability(state.scenario.analysis);
    if (layer === 'links') clearOverlayArray('links');
    if (layer === 'detections') clearOverlayArray('detections');
    if (layer === 'search') clearOverlayArray('searchCells');
  }

  function clearOverlayArray(key) {
    state.overlays[key].forEach(function (overlay) { overlay.setMap(null); });
    state.overlays[key] = [];
  }

  function setCameraMode(mode) {
    state.cameraMode = mode;
    state.lastFollowCameraAt = 0;
    if (els.hudPhase && state.scenario) {
      els.hudPhase.textContent = cameraLabel(mode);
    }
    document.querySelectorAll('[data-camera]').forEach(function (button) {
      button.classList.toggle('active', button.getAttribute('data-camera') === mode);
    });
    if (mode === 'fit' && state.scenario) {
      const bounds = new google.maps.LatLngBounds();
      state.scenario.route.points.forEach(function (p) { bounds.extend(p); });
      state.map.fitBounds(bounds, 70);
    }
  }

  function followCamera(frame) {
    if (state.cameraMode !== 'follow') return;
    const lead = (frame.convoy || [])[0];
    if (!lead) return;
    const now = window.performance ? window.performance.now() : Date.now();
    if (now - state.lastFollowCameraAt < FOLLOW_CAMERA_INTERVAL_MS) return;
    state.lastFollowCameraAt = now;

    const ahead = routeAheadPoint(lead.route_progress_pct || 0, frame.reroute && frame.reroute.recommended ? 1.4 : 2.2);
    const activeVectorId = frame.reroute && frame.reroute.active_vector_id;
    let activeVector = null;
    if (activeVectorId && frame.geo && frame.geo.attack_vectors) {
      activeVector = frame.geo.attack_vectors.find(function (candidate) {
        return candidate.id === activeVectorId;
      });
    }

    let center = ahead ? blendLatLng(lead.geo, ahead, 0.62) : lead.geo;
    if (activeVector && activeVector.end) {
      center = blendLatLng(center, activeVector.end, 0.18);
    }
    if ((state.map.getZoom() || 0) !== FOLLOW_LOCK_ZOOM) {
      state.map.setZoom(FOLLOW_LOCK_ZOOM);
    }
    state.map.panTo(center);
  }

  function updateMissionFromScenario(scenario) {
    const origin = scenario.origin && scenario.origin.label ? scenario.origin.label : els.origin.value;
    const destination = scenario.destination && scenario.destination.label ? scenario.destination.label : els.destination.value;
    const routeLabel = shortLabel(origin) + ' > ' + shortLabel(destination);
    const vectors = (scenario.analysis && scenario.analysis.attack_vectors) || [];
    const score = scenario.analysis && scenario.analysis.route_score;
    const phase = scenario.preflight && scenario.preflight.started ? 'Running' : 'Preflight';
    if (els.missionRoute) els.missionRoute.textContent = routeLabel;
    if (els.missionPhase) els.missionPhase.textContent = phase + ' / ' + cameraLabel(state.cameraMode);
    if (els.routeScore) els.routeScore.textContent = routeScoreLabel(score);
    if (els.activeRisk) els.activeRisk.textContent = riskLabel(maxVectorRisk(vectors));
    if (els.hudPhase) els.hudPhase.textContent = cameraLabel(state.cameraMode);
    if (els.hudDrones) {
      els.hudDrones.textContent =
        (scenario.settings.parent_drones || 0) + 'P / ' + (scenario.settings.small_drones || 0) + 'S';
    }
    if (els.hudThreats) els.hudThreats.textContent = String(vectors.length);
    updateMissionRibbon(
      phase === 'Running' ? 'Live data-aware route protection' : 'Data-aware preflight planning',
      phase === 'Running'
        ? 'Convoy edges are active; approved fixed sites, terrain, road context, and weather are informing route posture.'
        : ((score && score.summary) || 'Review route score, live/context data, and sparse edge candidate zones before approval.')
    );
  }

  function updateMissionFromFrame(frame) {
    const vectors = (frame.geo && frame.geo.attack_vectors) || [];
    const drones = frame.drones || [];
    const parents = drones.filter(function (drone) { return drone.tier === 'PARENT'; }).length;
    const smalls = drones.filter(function (drone) { return drone.tier === 'SMALL'; }).length;
    const tracks = (frame.sensing && frame.sensing.fused_tracks) || [];
    const edgeTracks = tracks.filter(function (track) { return track.edge_assisted; }).length;
    const recommended = frame.reroute && frame.reroute.recommended;
    const applied = frame.reroute && frame.reroute.applied;
    if (els.missionPhase) {
      els.missionPhase.textContent = (recommended ? 'Reroute' : 'Running') + ' / ' + cameraLabel(state.cameraMode);
    }
    if (els.hudPhase) els.hudPhase.textContent = cameraLabel(state.cameraMode);
    if (els.hudDrones) els.hudDrones.textContent = parents + 'P / ' + smalls + 'S';
    if (els.hudThreats) els.hudThreats.textContent = vectors.length + ' / ' + tracks.length;
    if (els.activeRisk) els.activeRisk.textContent = riskLabel(maxVectorRisk(vectors));
    if (els.routeScore && state.scenario) els.routeScore.textContent = routeScoreLabel(state.scenario.analysis.route_score);
    if (els.computeMode && edgeTracks) els.computeMode.textContent = edgeTracks + ' edge fused';
    if (recommended) {
      updateMissionRibbon('Auto reroute warning active', 'Fused drone track exceeded threshold; route adaptation is being applied live.');
    } else if (applied) {
      updateMissionRibbon('Live route revision ' + applied.route_revision, 'Convoy path now begins from the current position with active edge-aware coverage.');
    } else if (tracks.length) {
      updateMissionRibbon('Fused sensing track active', edgeTracks ? 'Edge-assisted parent fusion is classifying the synthetic vector.' : 'Parent drones are fusing reports locally.');
    } else {
      updateMissionRibbon('Route protection nominal', 'Parents are sectoring small drones around convoy and approved edge anchors.');
    }
  }

  function updateMissionRibbon(title, detail) {
    if (!els.missionRibbon) return;
    els.missionRibbon.innerHTML = '<strong>' + esc(title) + '</strong><span>' + esc(detail) + '</span>';
  }

  function updateRouteProgress(frame) {
    if (!state.overlays.routeProgress) return;
    const lead = (frame.convoy || [])[0];
    if (!lead) return;
    state.overlays.routeProgress.setPath(routeProgressPath(lead.route_progress_pct || 0, lead.geo));
  }

  function routeProgressPath(progressPct, leadPoint) {
    if (!state.scenario || !state.scenario.route || !state.scenario.route.samples) return leadPoint ? [leadPoint] : [];
    const samples = state.scenario.route.samples;
    if (!samples.length) return leadPoint ? [leadPoint] : [];
    const idx = Math.max(0, Math.min(samples.length - 1, Math.floor(progressPct / 100 * (samples.length - 1))));
    const path = samples.slice(0, idx + 1);
    if (leadPoint) path.push(leadPoint);
    return path;
  }

  function renderTimeline(frame, events) {
    if (!els.timelineStrip) return;
    const chips = [];
    const tracks = ((frame.sensing && frame.sensing.fused_tracks) || []).slice(-3);
    tracks.forEach(function (track) {
      chips.push({
        kind: track.edge_assisted ? 'edge' : 'track',
        text: 'Track ' + track.target_id + ' ' + Math.round(track.confidence * 100) + '% ' + (track.edge_assisted ? 'edge' : 'local'),
      });
    });
    if (frame.reroute && frame.reroute.recommended) {
      chips.push({ kind: 'warn', text: 'Auto reroute warning ' + (frame.reroute.active_vector_id || '') });
    }
    if (frame.reroute && frame.reroute.applied) {
      chips.push({ kind: 'edge', text: 'Route rev ' + frame.reroute.applied.route_revision + ' applied live' });
    }
    events.slice().reverse().slice(0, 4).forEach(function (event) {
      chips.push({ kind: 'track', text: event.parent_id + ' offload ' + event.chosen_target });
    });
    if (!chips.length) {
      els.timelineStrip.innerHTML = '<span class="timeline-empty">Live telemetry nominal.</span>';
      return;
    }
    els.timelineStrip.innerHTML = chips.slice(0, 8).map(function (chip) {
      return '<span class="timeline-chip ' + chip.kind + '">' + esc(chip.text) + '</span>';
    }).join('');
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
    els.approveAll.disabled = isBusy || !state.scenario;
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

  function shortLabel(value) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    if (text.length <= 26) return text || '--';
    return text.slice(0, 23) + '...';
  }

  function cameraLabel(mode) {
    if (mode === 'fit') return 'fit route';
    if (mode === 'free') return 'free pan';
    return 'follow';
  }

  function maxVectorRisk(vectors) {
    return vectors.reduce(function (maxRisk, vector) {
      return Math.max(maxRisk, Number(vector.risk || 0));
    }, 0);
  }

  function riskLabel(risk) {
    if (!risk) return '--';
    return Math.round(risk * 100) + '%';
  }

  function routeScoreLabel(score) {
    if (!score || score.overall == null) return '--';
    return Math.round(score.overall) + ' ' + String(score.grade || '').toUpperCase();
  }

  function scorePill(value) {
    const numeric = Number(value || 0);
    if (numeric >= 72) return 'edge';
    if (numeric >= 48) return 'warn';
    return 'track';
  }

  function scoreColor(score) {
    const numeric = Number(score || 0);
    if (numeric >= 72) return '#45d483';
    if (numeric >= 48) return '#efbf55';
    return '#ff625d';
  }

  function factorPercent(routeScore, key) {
    const factors = routeScore && routeScore.factor_scores;
    if (!factors || factors[key] == null) return '--';
    return Math.round(factors[key] * 100) + '%';
  }

  function decisionNarrative(score, deploy, zones, approvedCount) {
    const weak = ((score && score.factors) || []).slice().sort(function (a, b) {
      return (a.score || 0) - (b.score || 0);
    }).slice(0, 2).map(function (factor) { return factor.label; });
    const zoneText = zones.length ? zones.length + ' candidate zones visible before approval' : 'candidate zones pending';
    const approvalText = approvedCount ? approvedCount + ' approved fixed sites support scoring' : 'fixed sites do not support scoring until approved';
    return [
      score && score.summary ? score.summary : 'Planner score pending.',
      zoneText,
      approvalText,
      deploy && deploy.summary ? deploy.summary : '',
      weak.length ? 'Watch: ' + weak.join(', ') + '.' : '',
    ].filter(Boolean).join(' ');
  }

  function formatMeters(meters) {
    return meters >= 1000 ? (meters / 1000).toFixed(2) + ' km' : Math.round(meters) + ' m';
  }

  function searchCellLabel(cell) {
    if (!cell) return '--';
    const edge = cell.edge_anchor_id ? ', ' + cell.edge_anchor_id : '';
    return cell.pattern + ' @ ' + formatMeters(cell.route_distance_m) + ', ' + Math.round(cell.lateral_m) + ' m' + edge;
  }

  function edgeAnchorLabel(actor) {
    const id = actor.connected_edge_id || actor.edge_anchor_id;
    if (!id) return 'none';
    const quality = actor.edge_link_quality ? ' ' + Math.round(actor.edge_link_quality * 100) + '%' : '';
    return id + quality;
  }

  function rerouteSupportReason(proposal) {
    const reasons = proposal.reasons || [];
    const edgeReason = reasons.find(function (reason) { return reason.indexOf('edge') >= 0 || reason.indexOf('Edge') >= 0; });
    const connectReason = reasons.find(function (reason) { return reason.indexOf('connect') >= 0 || reason.indexOf('Connect') >= 0; });
    return [edgeReason, connectReason].filter(Boolean).join(' ');
  }

  function activeEdgeAnchor(frame) {
    const tracks = (frame.sensing && frame.sensing.fused_tracks) || [];
    const active = tracks.find(function (track) { return track.edge_anchor_id; });
    if (!active) return null;
    const edge = (frame.edges || []).find(function (candidate) { return candidate.id === active.edge_anchor_id; });
    return edge ? edge.geo : null;
  }

  function routeAheadPoint(progressPct, aheadPct) {
    if (!state.scenario || !state.scenario.route || !state.scenario.route.samples) return null;
    const samples = state.scenario.route.samples;
    if (!samples.length) return null;
    const targetPct = Math.max(0, Math.min(100, progressPct + aheadPct));
    const idx = Math.max(0, Math.min(samples.length - 1, Math.round(targetPct / 100 * (samples.length - 1))));
    return samples[idx];
  }

  function blendLatLng(a, b, amount) {
    const u = Math.max(0, Math.min(1, amount));
    return {
      lat: a.lat + (b.lat - a.lat) * u,
      lng: a.lng + (b.lng - a.lng) * u,
    };
  }

  function smoothOverlayPosition(overlay, target, setterName, getterName, durationMs) {
    const next = plainLatLng(target);
    if (!next) return;
    if (!overlay.__motionPoint) {
      const current = typeof overlay[getterName] === 'function' ? overlay[getterName]() : null;
      overlay.__motionPoint = plainLatLng(current) || next;
      overlay[setterName](next);
      return;
    }
    const from = overlay.__motionPoint;
    const distance = latLngDeltaMeters(from, next);
    if (distance < 0.25) {
      overlay.__motionPoint = next;
      overlay[setterName](next);
      return;
    }
    if (overlay.__motionFrame) window.cancelAnimationFrame(overlay.__motionFrame);
    const start = window.performance ? window.performance.now() : Date.now();
    const duration = Math.max(80, durationMs || MOTION_SMOOTH_MS);
    function step(now) {
      const elapsed = now - start;
      const t = Math.max(0, Math.min(1, elapsed / duration));
      const eased = t * t * (3 - 2 * t);
      const point = blendLatLng(from, next, eased);
      overlay.__motionPoint = point;
      overlay[setterName](point);
      if (t < 1) {
        overlay.__motionFrame = window.requestAnimationFrame(step);
      } else {
        overlay.__motionFrame = null;
        overlay.__motionPoint = next;
        overlay[setterName](next);
      }
    }
    overlay.__motionFrame = window.requestAnimationFrame(step);
  }

  function plainLatLng(value) {
    if (!value) return null;
    const lat = typeof value.lat === 'function' ? value.lat() : value.lat;
    const lng = typeof value.lng === 'function' ? value.lng() : value.lng;
    if (lat == null || lng == null) return null;
    return { lat: Number(lat), lng: Number(lng) };
  }

  function latLngDeltaMeters(a, b) {
    const latScale = 111320;
    const meanLat = ((a.lat + b.lat) / 2) * Math.PI / 180;
    const lngScale = Math.max(1, latScale * Math.cos(meanLat));
    const dx = (b.lng - a.lng) * lngScale;
    const dy = (b.lat - a.lat) * latScale;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function corridorPath(start, end, widthM) {
    const latScale = 111320;
    const meanLat = ((start.lat + end.lat) / 2) * Math.PI / 180;
    const lngScale = Math.max(1, latScale * Math.cos(meanLat));
    const dx = (end.lng - start.lng) * lngScale;
    const dy = (end.lat - start.lat) * latScale;
    const len = Math.max(1, Math.sqrt(dx * dx + dy * dy));
    const px = -dy / len * widthM / 2;
    const py = dx / len * widthM / 2;
    return [
      offsetLatLng(start, px, py, latScale, lngScale),
      offsetLatLng(end, px, py, latScale, lngScale),
      offsetLatLng(end, -px, -py, latScale, lngScale),
      offsetLatLng(start, -px, -py, latScale, lngScale),
    ];
  }

  function offsetLatLng(point, eastM, northM, latScale, lngScale) {
    return {
      lat: point.lat + northM / latScale,
      lng: point.lng + eastM / lngScale,
    };
  }

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }

  function edgeColor(status, type) {
    if (type === 'convoy_edge') return '#6cb7ff';
    if (status === 'approved' || status === 'moved') return '#45d483';
    if (status === 'rejected') return '#626b64';
    return '#efbf55';
  }

  function zoneColor(zone) {
    if (zone.status === 'approved' || zone.status === 'moved') return '#45d483';
    if (zone.status === 'rejected') return '#626b64';
    if (zone.deployability_class === 'high') return '#65e8ef';
    if (zone.deployability_class === 'low') return '#ff625d';
    return '#efbf55';
  }

  function terrainColor(severity) {
    if (severity === 'steep') return '#ff625d';
    if (severity === 'moderate') return '#efbf55';
    return '#6cb7ff';
  }

  function dataSourceIcon(stateValue) {
    const color = stateValue === 'available' || stateValue === 'derived'
      ? '#45d483'
      : (stateValue === 'partial' ? '#efbf55' : '#626b64');
    return {
      path: google.maps.SymbolPath.CIRCLE,
      scale: 7,
      fillColor: color,
      fillOpacity: .94,
      strokeColor: '#061012',
      strokeWeight: 2,
    };
  }

  function vectorIcon(vector) {
    const color = vector.type === 'synthetic_gap_pressure' ? '#efbf55' : '#ff625d';
    return {
      path: 'M 0,-12 L 4,-4 L 12,0 L 4,4 L 0,12 L -4,4 L -12,0 L -4,-4 Z',
      scale: 1.05,
      fillColor: color,
      fillOpacity: .95,
      strokeColor: '#ffffff',
      strokeWeight: 1.5,
    };
  }

  function edgeIcon(status, type) {
    const convoy = type === 'convoy_edge';
    return {
      path: convoy ? 'M -7,-4 L 7,-4 L 7,4 L 2,4 L 0,8 L -2,4 L -7,4 Z' : 'M 0,-13 L 8,8 L 3,8 L 0,13 L -3,8 L -8,8 Z',
      scale: convoy ? 1.2 : 1.05,
      rotation: convoy ? 0 : 0,
      fillColor: edgeColor(status, type),
      fillOpacity: status === 'rejected' ? 0.45 : 1,
      strokeColor: '#031012',
      strokeWeight: 2,
    };
  }

  function droneIcon(drone) {
    const parent = drone.tier === 'PARENT';
    return {
      path: parent ? 'M 0,-18 L 14,12 L 4,8 L 0,16 L -4,8 L -14,12 Z' : 'M 0,-7 L 7,0 L 0,7 L -7,0 Z',
      scale: parent ? 1.08 : 1.25,
      rotation: ((drone.pose && drone.pose.yaw) || 0) * 180 / Math.PI,
      fillColor: parent ? '#6cb7ff' : taskColor(drone.current_task),
      fillOpacity: .95,
      strokeColor: parent ? '#d7fbff' : '#061012',
      strokeWeight: parent ? 1.7 : 1.4,
    };
  }

  function convoyIcon() {
    return {
      path: 'M -12,-7 L 8,-7 L 14,0 L 8,7 L -12,7 Z',
      scale: 1.1,
      fillColor: '#efbf55',
      fillOpacity: 1,
      strokeColor: '#061012',
      strokeWeight: 2,
    };
  }

  function targetIcon() {
    return {
      path: 'M 0,-9 L 3,-3 L 9,0 L 3,3 L 0,9 L -3,3 L -9,0 L -3,-3 Z',
      scale: 1.05,
      fillColor: '#ff625d',
      fillOpacity: .9,
      strokeColor: '#ffffff',
      strokeWeight: 1,
    };
  }

  function taskColor(task) {
    if (String(task).indexOf('investigate_') >= 0) return '#ff625d';
    if (String(task).indexOf('screen_') >= 0) return '#efbf55';
    if (String(task).indexOf('sector_0') >= 0) return '#eef5ec';
    if (String(task).indexOf('sector_1') >= 0) return '#45d483';
    if (String(task).indexOf('sector_2') >= 0) return '#efbf55';
    return '#d3a5ff';
  }

  function statusClass(status) {
    if (status === 'approved' || status === 'moved') return 'edge';
    if (status === 'rejected') return 'muted';
    return 'warn';
  }

  boot();
}());
