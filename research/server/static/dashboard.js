/* Read-only telemetry display. No sensor, location, engine or control APIs. */
"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const sessions = new Map();
  const MAX_POINTS = 600;
  let selected = "", connected = false, ws, retry = 0, retryTimer, stopped = false;
  let following = true, street = false, tileFailed = false, leaflet, tileLayer, marker, halo;
  let pathLayers = [], lastFit = null, lastRenderSequence = -1, localViewport = null;
  const stateColor = state => state === "IDR_ACTIVE" || state === "GNSS_DEGRADED" ? "#f2b95e" : /VERIFY|RECOVER/.test(state || "") ? "#b89af2" : state === "ERROR" ? "#f17878" : state === "GNSS_ACTIVE" ? "#43d5c1" : "#8da5b5";
  const human = text => text == null ? "Unavailable" : String(text).replaceAll("_", " ");
  const number = (value, digits = 1, unit = "") => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : "—";
  const put = (id, value) => { $(id).textContent = value; };
  const duration = value => { if (!Number.isFinite(value)) return "--:--"; const seconds = Math.max(0, Math.floor(value)); return `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`; };
  const utcTime = value => { if (!value) return "—"; const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? "—" : parsed.toLocaleTimeString([], {hour12:false}); };
  const current = () => sessions.get(selected);
  const availablePoint = p => p && ((p.latitude != null && p.longitude != null) || (p.local_east_m != null && p.local_north_m != null));

  function updateSessions(packet) {
    const incoming = packet.type === "telemetry" ? [packet.session] : packet.sessions || [];
    if (packet.type === "snapshot" || packet.type === "status") {
      const ids = new Set(incoming.map(s => s.session_id));
      for (const id of sessions.keys()) if (!ids.has(id)) sessions.delete(id);
    }
    for (const session of incoming) {
      const old = sessions.get(session.session_id);
      const history = session.history || old?.history || [];
      const latest = session.latest;
      const point = packet.point || (latest && { ...latest.estimated_position, state:latest.navigation.localization_state, heading_deg:latest.motion.heading_deg, sequence:latest.sequence, timestamp_ns:latest.timestamp_ns });
      if (point && (!history.length || history[history.length - 1].sequence < point.sequence)) history.push(point);
      if (history.length > MAX_POINTS) history.splice(0, history.length - MAX_POINTS);
      sessions.set(session.session_id, {...old, ...session, history, receivedAt:performance.now()});
    }
    const select = $("sessionSelect");
    const ids = [...sessions.keys()];
    if (!sessions.has(selected)) selected = ids[ids.length - 1] || "";
    const oldOptions = [...select.options].map(x => x.value).join(",");
    if (oldOptions !== (ids.length ? ids.join(",") : "")) {
      select.replaceChildren();
      for (const id of ids.length ? ids : [""]) {
        const option = document.createElement("option"); option.value = id; option.textContent = id ? `Phone · ${id.slice(0, 8)}` : "Waiting for phone"; select.append(option);
      }
    }
    select.value = selected;
    render();
  }

  function connect() {
    if (stopped) return;
    ws = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/dashboard`);
    ws.onopen = () => { connected = true; retry = 0; render(); };
    ws.onmessage = event => { try { const packet = JSON.parse(event.data); if (["snapshot", "status", "telemetry"].includes(packet.type)) updateSessions(packet); } catch (_) { /* Ignore an invalid server frame without changing the last estimate. */ } };
    ws.onclose = () => { connected = false; render(); if (!stopped) retryTimer = setTimeout(connect, Math.min(15000, 750 * (2 ** Math.min(retry++, 5))) + Math.random() * 250); };
    ws.onerror = () => ws.close();
  }

  function render() {
    const s = current(), d = s?.latest;
    const age = s ? (s.last_update_age_s || 0) + (performance.now() - s.receivedAt) / 1000 : null;
    const fresh = connected && s?.connection === "CONNECTED" && age <= 3;
    put("connectionText", !connected ? "RECONNECTING TO SERVER" : !s ? "WAITING FOR PHONE" : s.connection === "OFFLINE" ? "PHONE OFFLINE" : fresh ? "PHONE CONNECTED" : "PHONE STREAM STALE");
    $("connectionDot").className = `dot ${fresh ? "active" : s ? "stale" : ""}`;
    put("updateAge", s ? `Last update ${age < 1 ? Math.round(age * 1000) + " ms" : age.toFixed(1) + " s"} ago` : "No telemetry received");
    $("staleOverlay").hidden = !d || fresh;
    put("staleOverlay", !connected || s?.connection === "OFFLINE" ? "LAST KNOWN ESTIMATE · STREAM OFFLINE" : "LAST KNOWN ESTIMATE · STREAM STALE");
    put("sessionTime", duration(s ? s.session_duration_s + (performance.now() - s.receivedAt) / 1000 : null));
    if (!d) { clearDisplay(); return; }
    put("mode", d.mode === "DEMO" ? "DEMO REPLAY" : "LIVE PHONE"); $("mode").className = `tag ${d.mode === "DEMO" ? "demo" : "live"}`;
    put("sequence", String(d.sequence)); put("recording", d.recording ? "RECORDING" : "NOT RECORDING");
    put("navState", human(d.navigation.localization_state));
    $("navState").style.color = stateColor(d.navigation.localization_state);
    document.querySelector(".state-panel").style.borderTopColor = stateColor(d.navigation.localization_state);
    put("gnssState", human(d.navigation.gnss_state)); put("confidence", human(d.navigation.confidence));
    put("alignment", human(d.navigation.alignment_state)); put("motionState", human(d.navigation.motion_state));
    put("speed", number(d.motion.speed_kmh)); put("speedMps", number(d.motion.speed_mps, 1, " m/s"));
    put("heading", number(d.motion.heading_deg, 0, "°")); put("uncertainty", number(d.navigation.uncertainty_m, 1, " m")); put("drTime", number(d.navigation.dr_duration_s, 1, " s"));
    const aiLabels = {WARMING:"AI warming up",ASSISTED:"AI assist active",SAFETY_FALLBACK:"AI safety fallback",UNAVAILABLE:"AI unavailable"};
    put("aiState", aiLabels[d.ai.state] || human(d.ai.state)); put("mlState", human(d.ai.ml_state)); put("ood", number(d.ai.ood_exceedance, 2));
    $("aiIndicator").style.background = d.ai.state === "ASSISTED" ? "#43d5c1" : d.ai.state === "SAFETY_FALLBACK" ? "#f2b95e" : "#94a9b9";
    put("accel", number(d.sensors.accelerometer_hz, 1, " Hz")); put("gyro", number(d.sensors.gyroscope_hz, 1, " Hz")); put("mag", number(d.sensors.magnetometer_hz, 1, " Hz")); put("runtime", number(d.sensors.runtime_hz, 1, " Hz"));
    const g = d.gnss_observability;
    put("satellites", `${number(g.satellites_visible, 0)} / ${number(g.satellites_used, 0)}`); put("satStatus", g.status_available == null ? "Unavailable" : g.status_available ? "Available" : "Unavailable");
    put("callbacks", number(g.physical_callback_count, 0)); put("callbackAge", number(g.latest_callback_age_s, 1, " s")); put("realMask", g.blackout_masks_real_fix == null ? "Unavailable" : g.blackout_masks_real_fix ? "YES" : "NO");
    put("engine", `${number(d.engine.avg_ms, 2)} / ${number(d.engine.p95_ms, 2)} ms`); put("battery", number(d.device.battery_percent, 0, "%")); put("temperature", number(d.device.battery_temperature_c, 1, " °C")); put("thermal", human(d.device.thermal_state));
    put("fieldMap", `${human(d.field_test_state)} / ${human(d.map_mode)}`);
    const p = d.estimated_position;
    put("coordinates", p.latitude != null ? `${p.latitude.toFixed(6)}°, ${p.longitude.toFixed(6)}°` : p.local_east_m != null ? `E ${p.local_east_m.toFixed(1)} m · N ${p.local_north_m.toFixed(1)} m` : "POSITION UNAVAILABLE");
    $("mapEmpty").hidden = availablePoint(p);
    if (lastRenderSequence !== `${selected}:${d.sequence}`) {
      lastRenderSequence = `${selected}:${d.sequence}`;
      renderTimeline(s.timeline || []); renderEvents(s.events || []);
      renderMap(s);
    }
  }

  function clearDisplay() {
    for (const id of ["sequence","speed","speedMps","heading","uncertainty","drTime","confidence","alignment","motionState","ood","accel","gyro","mag","runtime","callbacks","callbackAge","engine","battery","temperature","thermal","fieldMap"]) put(id,"—");
    put("mode","NO STREAM"); $("mode").className="tag"; put("navState","WAITING FOR PHONE"); $("navState").style.color="#94a9b9";
    put("gnssState","GNSS unavailable"); put("aiState","No snapshot yet"); put("mlState","Unavailable until the phone connects"); put("satellites","— / —"); put("satStatus","Unavailable"); put("realMask","Unavailable"); put("recording","NOT RECORDING"); put("coordinates","POSITION UNAVAILABLE");
    $("mapEmpty").hidden=false; renderTimeline([]);renderEvents([]); clearMap();drawLocal();
  }

  function renderTimeline(items) {
    const box = $("timeline"); box.replaceChildren();
    if (!items.length) { const el=document.createElement("span");el.className="empty-inline";el.textContent="GNSS → IDR → recovery transitions will appear here.";box.append(el);return; }
    items.slice(-12).forEach((entry, index) => { if(index){const arrow=document.createElement("span");arrow.className="timeline-arrow";arrow.textContent="→";box.append(arrow);}const chip=document.createElement("div");chip.className="timeline-item";chip.style.color=stateColor(entry.state);chip.style.borderColor=stateColor(entry.state)+"55";chip.textContent=human(entry.state);const time=document.createElement("small");time.textContent=utcTime(entry.wall_time_utc);chip.append(time);box.append(chip); });
    box.scrollLeft=box.scrollWidth;
  }
  function renderEvents(items) {
    const box=$("events");box.replaceChildren();put("eventCount",`${items.length} events`);
    if (!items.length){const li=document.createElement("li");li.className="empty-inline";li.textContent="Meaningful state changes appear here. Telemetry frames do not flood this log.";box.append(li);return;}
    for(const item of [...items].reverse()){const li=document.createElement("li"),time=document.createElement("time"),label=document.createElement("span");time.textContent=utcTime(item.wall_time_utc);label.textContent=human(item.message);li.append(time,label);box.append(li);}
  }

  function initializeLeaflet() {
    if(leaflet || !window.L)return;
    leaflet=L.map("map",{zoomControl:true,attributionControl:true});
    leaflet.on("dragstart",()=>setFollow(false));
    tileLayer=L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',maxZoom:19});
    tileLayer.on("tileerror",()=>{if(street){tileFailed=true;street=false;setView();}});
  }
  function clearMap() {
    if(leaflet){pathLayers.forEach(layer=>layer.remove());pathLayers=[];if(marker){marker.remove();marker=null;}if(halo){halo.remove();halo=null;}}
  }
  function renderMap(s) {
    drawLocal();
    if(!street)return;
    initializeLeaflet();
    const p=s.latest.estimated_position;
    if(!leaflet || p.latitude==null){street=false;setView();return;}
    if(!leaflet.hasLayer(tileLayer))tileLayer.addTo(leaflet);
    if(!lastFit || following){leaflet.setView([p.latitude,p.longitude],lastFit?leaflet.getZoom():17,{animate:false});lastFit=[p.latitude,p.longitude];}
    clearMap();
    let segment=[],lastState=null,lastPoint=null;
    const flush=()=>{if(segment.length>1)pathLayers.push(L.polyline(segment,{color:stateColor(lastState),weight:4,opacity:.9,dashArray:/VERIFY|RECOVER/.test(lastState||"")?"7 5":null}).addTo(leaflet));};
    for(const point of s.history){if(point.latitude==null){flush();segment=[];lastPoint=null;continue;}if(point.state!==lastState){flush();segment=lastPoint?[lastPoint]:[];lastState=point.state;}lastPoint=[point.latitude,point.longitude];segment.push(lastPoint);}flush();
    const heading=s.latest.motion.heading_deg||0,color=stateColor(s.latest.navigation.localization_state);
    marker=L.marker([p.latitude,p.longitude],{icon:L.divIcon({className:"vehicle-shell",html:`<div class="vehicle" style="transform:rotate(${heading}deg);--vehicle-color:${color}"></div>`,iconSize:[24,30],iconAnchor:[12,15]})}).addTo(leaflet);
    const uncertainty=s.latest.navigation.uncertainty_m;
    if(uncertainty!=null)halo=L.circle([p.latitude,p.longitude],{radius:uncertainty,color,weight:1,opacity:.6,fillColor:color,fillOpacity:.09,interactive:false}).addTo(leaflet);
  }
  function setView() {
    $("map").style.display=street?"block":"none";$("localMap").style.display=street?"none":"block";
    put("viewToggle",street?"Local view":"Street map");put("offlineBanner",street?"OPENSTREETMAP · ESTIMATE FROM PHONE":tileFailed?"MAP TILES UNAVAILABLE · LOCAL VIEW":"LOCAL VIEW · WORKS WITHOUT MAP TILES");
    if(street){initializeLeaflet();leaflet?.invalidateSize();}else if(leaflet&&tileLayer&&leaflet.hasLayer(tileLayer)){leaflet.removeLayer(tileLayer);}
    if(current())renderMap(current());else drawLocal();
  }
  function setFollow(value){following=value;$("follow").setAttribute("aria-pressed",String(value));put("follow",value?"Follow on":"Follow paused");}
  function localPoints(s) {
    const history=(s?.history||[]).filter(availablePoint),origin=history.find(p=>p.latitude!=null);
    return history.map(p=>p.local_east_m!=null?{x:p.local_east_m,y:p.local_north_m,state:p.state}:origin?{x:(p.longitude-origin.longitude)*111320*Math.cos(origin.latitude*Math.PI/180),y:(p.latitude-origin.latitude)*111320,state:p.state}:null).filter(Boolean);
  }
  function drawLocal() {
    const canvas=$("localMap"),rect=canvas.getBoundingClientRect();if(!rect.width||!rect.height)return;
    const ratio=window.devicePixelRatio||1;canvas.width=rect.width*ratio;canvas.height=rect.height*ratio;
    const c=canvas.getContext("2d");c.scale(ratio,ratio);const w=rect.width,h=rect.height;c.fillStyle="#09151e";c.fillRect(0,0,w,h);
    c.strokeStyle="#19303c";c.lineWidth=.6;for(let x=0;x<w;x+=44){c.beginPath();c.moveTo(x,0);c.lineTo(x,h);c.stroke();}for(let y=0;y<h;y+=44){c.beginPath();c.moveTo(0,y);c.lineTo(w,y);c.stroke();}
    c.fillStyle="#728d9e";c.font="10px Segoe UI";c.fillText("N ↑",w-37,25);
    const s=current(),points=localPoints(s);if(!points.length)return;
    const last=points[points.length-1],u=s.latest.navigation.uncertainty_m||0;
    if(following||!localViewport){const xs=points.map(p=>p.x),ys=points.map(p=>p.y);const span=Math.max(60,Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys),Math.min(u*2.4,100000));localViewport={cx:(Math.max(...xs)+Math.min(...xs))/2,cy:(Math.max(...ys)+Math.min(...ys))/2,scale:Math.min(w-80,h-90)/span};}
    const {cx,cy,scale}=localViewport;const xy=p=>[w/2+(p.x-cx)*scale,h/2-(p.y-cy)*scale];
    for(let i=1;i<points.length;i++){c.beginPath();c.strokeStyle=stateColor(points[i].state);c.lineWidth=3;c.setLineDash(/VERIFY|RECOVER/.test(points[i].state)?[6,4]:[]);c.moveTo(...xy(points[i-1]));c.lineTo(...xy(points[i]));c.stroke();}c.setLineDash([]);
    const [x,y]=xy(last),color=stateColor(s.latest.navigation.localization_state);
    if(u>0){c.beginPath();c.arc(x,y,Math.min(u*scale,Math.max(w,h)*3),0,2*Math.PI);c.fillStyle=color+"14";c.fill();c.strokeStyle=color+"70";c.lineWidth=1;c.stroke();}
    c.save();c.translate(x,y);c.rotate((s.latest.motion.heading_deg||0)*Math.PI/180);c.beginPath();c.moveTo(0,-12);c.lineTo(9,10);c.lineTo(0,5);c.lineTo(-9,10);c.closePath();c.fillStyle=color;c.fill();c.strokeStyle="#eff8fa";c.lineWidth=1;c.stroke();c.restore();
    const scaleM=Math.pow(10,Math.floor(Math.log10(80/scale)));const scalePx=scaleM*scale;c.strokeStyle="#9fb3c0";c.beginPath();c.moveTo(18,h-22);c.lineTo(18+scalePx,h-22);c.stroke();c.fillStyle="#9fb3c0";c.fillText(`${scaleM.toLocaleString()} m · local metric view`,18,h-30);
  }

  $("sessionSelect").addEventListener("change",event=>{selected=event.target.value;lastRenderSequence=-1;lastFit=null;localViewport=null;clearMap();render();});
  $("follow").addEventListener("click",()=>{setFollow(!following);if(current())renderMap(current());});
  $("recenter").addEventListener("click",()=>{setFollow(true);localViewport=null;lastFit=null;if(current())renderMap(current());});
  $("viewToggle").addEventListener("click",()=>{street=!street;tileFailed=false;setView();});
  put("phoneEndpoint",`${location.protocol==="https:"?"wss":"ws"}://${location.hostname === "127.0.0.1" || location.hostname === "localhost" ? "<LAPTOP_IP>" : location.hostname}:${location.port || (location.protocol==="https:"?443:80)}/ws/telemetry`);
  new ResizeObserver(()=>{drawLocal();leaflet?.invalidateSize();}).observe($("map-stage")||document.querySelector(".map-stage"));
  const ticker=setInterval(render,500);
  window.addEventListener("pagehide",()=>{stopped=true;clearTimeout(retryTimer);clearInterval(ticker);ws?.close();});
  drawLocal();connect();
})();
