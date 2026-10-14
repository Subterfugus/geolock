"use strict";
const $ = (s) => document.querySelector(s);
const COLORS = { high: "--high", medium: "--medium", low: "--low" };
const ANALYST = { claude: { color: "--claude", letter: "C" }, chatgpt: { color: "--chatgpt", letter: "G" } };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const pct = (p) => (p >= 0.995 ? "99%" : p < 0.01 ? "<1%" : Math.round(p * 100) + "%");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ------------------------------------------------------------------ map
const map = L.map("map", { worldCopyJump: true, zoomControl: true, minZoom: 2 }).setView([25, 10], 2);
const offline = L.layerGroup().addTo(map);
const online = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "© OpenStreetMap contributors" });
L.control.layers({ "Offline map": offline, "OpenStreetMap (needs internet)": online }, null,
                 { position: "topright" }).addTo(map);

const landStyle = () => ({ color: css("--border"), weight: 0.7, fillColor: css("--land"), fillOpacity: 1 });
let countriesLayer, admin1Layer, labels = L.layerGroup();
fetch("/data/countries.geojson").then((r) => r.json()).then((gj) => {
  countriesLayer = L.geoJSON(gj, { style: landStyle, interactive: false }).addTo(offline);
  for (const f of gj.features) {
    const p = f.properties;
    if (p.lx == null) continue;
    L.tooltip({ permanent: true, direction: "center", className: "country-label", opacity: 1 })
      .setLatLng([p.ly, p.lx]).setContent(esc(p.name)).addTo(labels).options.minlabel = p.minlabel;
  }
  updateLabels();
});
function updateLabels() {
  const z = map.getZoom();
  labels.eachLayer((t) => { const show = t.options.minlabel <= z + 0.6;
    if (show && !offline.hasLayer(t)) offline.addLayer(t); else if (!show) offline.removeLayer(t); });
  if (z >= 5 && !admin1Layer) {
    admin1Layer = "loading";
    fetch("/data/admin1.geojson").then((r) => r.json()).then((gj) => {
      admin1Layer = L.geoJSON(gj, { style: { color: css("--border"), weight: 0.4, dashArray: "2 3",
                                             fill: false }, interactive: false });
      updateLabels();
    });
  }
  if (admin1Layer && admin1Layer !== "loading") {
    if (z >= 5) offline.addLayer(admin1Layer); else offline.removeLayer(admin1Layer);
  }
}
map.on("zoomend", updateLabels);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => countriesLayer && countriesLayer.setStyle(landStyle));

let overlay = L.layerGroup().addTo(map);
let heat = null;

// ----------------------------------------------------------------- state
const history = [];
let current = null;
let selected = 0;

fetch("/api/status").then((r) => r.json()).then((s) => {
  $("#device").textContent = "Running on " + ({ GPU: "Arc GPU", NPU: "NPU", CPU: "CPU" }[s.device] || s.device);
  $("#device").title = "Available: " + s.available_devices.join(", ");
  if (!s.vlm) {
    $("#opt-vlm").disabled = true;
    $("#vlm-label").classList.add("disabled");
    $("#vlm-label").title = "Not installed. Run setup with --vlm to enable.";
  }
  for (const [key, st] of Object.entries(s.analysts || {})) {
    const box = $(`#ask-${key}`), label = $(`#ask-${key}-label`);
    if (!box) continue;
    label.title = st.detail || "";
    // Always starts unticked: each use spends the user's Claude / ChatGPT plan.
    box.checked = false;
    if (!st.available) { box.disabled = true; label.classList.add("disabled"); }
  }
  updateAskNote();
}).catch(() => { $("#device").textContent = "offline?"; });

const askBoxes = () => [...document.querySelectorAll("#ask-row input[data-provider]")];
function updateAskNote() { $("#ask-note").hidden = !askBoxes().some((b) => b.checked); }
askBoxes().forEach((b) => b.addEventListener("change", updateAskNote));

// ---------------------------------------------------------------- upload
const drop = $("#drop");
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("drag"); });
drop.addEventListener("dragleave", () => drop.classList.remove("drag"));
drop.addEventListener("drop", (e) => {
  e.preventDefault(); drop.classList.remove("drag");
  const f = [...e.dataTransfer.files].find((f) => f.type.startsWith("image/") || /\.(heic|heif)$/i.test(f.name));
  if (f) analyse(f);
});
$("#file").addEventListener("change", (e) => e.target.files[0] && analyse(e.target.files[0]));
document.addEventListener("paste", (e) => {
  const item = [...e.clipboardData.items].find((i) => i.type.startsWith("image/"));
  if (item) analyse(item.getAsFile());
});

async function analyse(file) {
  const url = URL.createObjectURL(file);
  showPreview(url);
  $("#error").hidden = true;
  $("#busy").hidden = false;
  const ask = askBoxes().filter((b) => b.checked && !b.disabled).map((b) => b.dataset.provider);
  const askNames = ask.map((p) => p === "claude" ? "Claude" : "ChatGPT").join(" and ");
  $("#busy-text").textContent = ask.length ? `Analysing, then asking ${askNames} (can take a minute)…`
    : $("#opt-vlm").checked ? "Analysing (deep analysis can take a while)…" : "Analysing…";
  const fd = new FormData();
  fd.append("file", file);
  fd.append("ocr", $("#opt-ocr").checked);
  fd.append("vlm", $("#opt-vlm").checked);
  fd.append("exif_gps", $("#opt-exif").checked);
  fd.append("ask", ask.join(","));
  fd.append("share_local", $("#opt-share").checked);
  try {
    const r = await fetch("/api/locate", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.statusText);
    const entry = { url: data.preview || url, data, name: file.name || "pasted image" };
    delete data.preview;
    history.unshift(entry);
    show(entry);
  } catch (err) {
    $("#error").textContent = "Couldn't analyse this photo: " + err.message;
    $("#error").hidden = false;
  } finally {
    $("#busy").hidden = true;
  }
}

function showPreview(url) {
  $("#preview").src = url;
  $("#preview").hidden = false;
  drop.classList.add("has-image");
  $("#boxes").hidden = true;
}

// ---------------------------------------------------------------- render
function show(entry) {
  current = entry;
  selected = 0;
  showPreview(entry.url);
  const d = entry.data;
  $("#results").hidden = false;
  renderGuesses(d);
  renderAnalysts(d);
  renderCountries(d);
  renderClues(d);
  $("#scene").innerHTML = d.scene.map((s) => `<span class="chip" title="${esc(s.attribute)}">${esc(s.value)} <span>${pct(s.prob)}</span></span>`).join("");
  const t = d.timings;
  $("#timings").textContent = `Device ${d.device} · CLIP ${t.clip_ms} ms` + (t.ocr_ms != null ? ` · OCR ${t.ocr_ms} ms` : "") +
    (t.vlm_ms != null ? ` · VLM ${t.vlm_ms} ms` : "") +
    (t.llm_ms != null ? ` · second opinions ${(t.llm_ms / 1000).toFixed(0)} s` : "") + ` · total ${t.total_ms} ms · ${d.image.width}×${d.image.height}` +
    (d.exif.camera ? ` · ${d.exif.camera}` : "") + (d.exif.datetime ? ` · ${d.exif.datetime}` : "");
  $("#vlm-raw").hidden = !d.vlm_raw;
  $("#vlm-raw").textContent = d.vlm_raw || "";
  drawOcrBoxes(d);
  drawMap(d);
  renderHistory();
}

function color(g) { return css(COLORS[g.label]); }

function placeName(g) {
  const parts = [];
  if (g.place && g.place.km < 60) parts.push(g.place.name);
  if (g.region && g.region !== parts[0]) parts.push(g.region);
  return { main: parts.join(", ") || g.country, sub: parts.length ? g.country : (g.continent || "") };
}

function whyList(g) {
  return `<ul class="why">` + g.why.map((w) => {
    const [cls, icon] = w.effect > 0 ? ["pos", "✓"] : w.effect < 0 ? ["neg", "✗"] : ["neu", "·"];
    return `<li><span class="i ${cls}">${icon}</span><span>${esc(w.text)}</span></li>`;
  }).join("") + `</ul>`;
}

function renderGuesses(d) {
  const g = d.guesses[selected];
  const n = placeName(g);
  const near = g.place && g.place.km >= 60 ? ` · ${Math.round(g.place.km)} km from ${esc(g.place.name)}` : "";
  const exifNote = g.km_from_exif != null ? `<div class="sub">EXIF GPS is ${Math.round(g.km_from_exif)} km from this guess.</div>` : "";
  $("#best").innerHTML = `
    <div class="eyebrow">${selected === 0 ? "Best guess" : "Guess #" + (selected + 1)}</div>
    <div class="place">${esc(n.main)}</div>
    <div class="sub">${esc(n.sub)}${near}</div>
    <div class="meter"><div style="width:${Math.max(2, g.confidence * 100)}%;background:${color(g)}"></div></div>
    <div class="conf"><span><b class="${g.label}">${pct(g.confidence)}</b> confidence (${g.label})</span>
      <span>within ~${Math.round(g.radius_km)} km</span></div>
    ${exifNote}
    ${whyList(g)}`;
  $("#best").onclick = () => focusGuess(selected);
  $("#guesses").innerHTML = d.guesses.map((x, i) => {
    const m = placeName(x);
    return `<li data-i="${i}" class="${i === selected ? "sel" : ""}">
      <span class="num" style="background:${color(x)}">${i + 1}</span>
      <span>${esc(m.main)}<div class="small">${esc(m.sub)} · ±${Math.round(x.radius_km)} km</div></span>
      <span class="pct">${pct(x.confidence)}</span></li>`;
  }).join("");
  $("#guesses").querySelectorAll("li").forEach((li) => li.onclick = () => {
    selected = +li.dataset.i; renderGuesses(d); focusGuess(selected); });
}

function renderAnalysts(d) {
  const list = d.analysts || [];
  $("#analysts").innerHTML = list.map((a, ai) => {
    const style = `--who:var(${ANALYST[a.provider].color})`;
    const meta = [a.model, a.ms != null ? Math.round(a.ms / 1000) + " s" : null].filter(Boolean).join(" · ");
    if (!a.ok) return `<div class="analyst" style="${style}"><div class="head"><span class="who">${esc(a.name)}</span>
      <span class="meta">${esc(meta)}</span></div><div class="err">No answer: ${esc(a.error)}</div></div>`;
    const guesses = a.guesses.map((g, gi) => `<li data-a="${ai}" data-g="${gi}">${esc([g.place, g.country].filter(Boolean).join(", "))}
      <span class="pct">${pct(g.confidence)} · ±${Math.round(g.radius_km)} km${g.km_from_exif != null ? ` · ${Math.round(g.km_from_exif)} km from EXIF` : ""}</span></li>`).join("");
    const clues = a.clues.length ? `<details><summary>What ${esc(a.name)} saw (${a.clues.length})</summary><ul>` +
      a.clues.map((c) => `<li><b>${esc(c.clue)}</b>${c.suggests ? ": " + esc(c.suggests) : ""}</li>`).join("") + `</ul></details>` : "";
    return `<div class="analyst" style="${style}"><div class="head"><span class="who">${esc(a.name)}'s view</span>
      <span class="meta" title="${esc(a.via)}">${esc(meta)}</span></div>
      <div class="reason">${esc(a.reasoning)}</div><ol>${guesses}</ol>${clues}</div>`;
  }).join("");
  $("#analysts").querySelectorAll("li[data-a]").forEach((li) => li.onclick = () => {
    const g = list[+li.dataset.a].guesses[+li.dataset.g];
    map.flyTo([g.lat, g.lon], g.radius_km < 30 ? 9 : g.radius_km < 100 ? 7 : 5, { duration: 0.8 });
  });
}

function renderCountries(d) {
  const max = Math.max(...d.countries.map((c) => c.prob), 0.01);
  $("#countries").innerHTML = d.countries.slice(0, 6).map((c) => `
    <div class="bar" title="CLIP zero-shot alone: ${pct(c.clip_prob)}">
      <span class="name">${esc(c.name)}</span>
      <span class="track"><span class="fill" style="display:block;width:${(c.prob / max) * 100}%"></span></span>
      <span class="v">${pct(c.prob)}</span></div>`).join("");
}

function renderClues(d) {
  const items = [...d.clues].sort((a, b) => b.strength - a.strength);
  $("#clues").innerHTML = items.map((c) => {
    const where = c.countries.length
      ? `<div class="c">Points to: ${c.countries.slice(0, 6).map((x) => esc(x.name)).join(", ")}${c.n_countries > 6 ? ` +${c.n_countries - 6} more` : ""}</div>` : "";
    return `<li class="${c.strength >= 0.4 ? "strong" : ""}"><div class="t"><span class="kind">${esc(c.kind)}</span>${esc(c.title)}</div>
      ${c.detail ? `<div class="d">${esc(c.detail)}</div>` : ""}${where}</li>`;
  }).join("") || `<li><div class="d">No specific clues found; the guess rests on overall visual similarity.</div></li>`;
}

function drawOcrBoxes(d) {
  const img = $("#preview"), cv = $("#boxes");
  const draw = () => {
    if (!d.ocr || !d.ocr.length) { cv.hidden = true; return; }
    const r = img.getBoundingClientRect();
    const s = Math.min(r.width / d.image.width, r.height / d.image.height);
    const ox = (r.width - d.image.width * s) / 2, oy = (r.height - d.image.height * s) / 2;
    cv.width = r.width; cv.height = r.height; cv.hidden = false;
    const ctx = cv.getContext("2d", { willReadFrequently: false });
    ctx.strokeStyle = "#ffd400"; ctx.lineWidth = 1.5;
    for (const l of d.ocr) {
      ctx.beginPath();
      l.box.forEach(([x, y], i) => (i ? ctx.lineTo : ctx.moveTo).call(ctx, ox + x * s, oy + y * s));
      ctx.closePath(); ctx.stroke();
    }
  };
  if (img.complete) draw(); else img.onload = draw;
}

function drawMap(d) {
  overlay.clearLayers();
  if (heat) { map.removeLayer(heat); heat = null; }
  if (d.heat.length) {
    heat = L.heatLayer(d.heat, { radius: 18, blur: 22, maxZoom: 6, minOpacity: 0.25,
      gradient: { 0.2: "#3b82f6", 0.5: "#22c55e", 0.75: "#facc15", 1: "#ef4444" } }).addTo(map);
  }
  const pts = [];
  [...d.guesses].reverse().forEach((g) => {
    const i = d.guesses.indexOf(g);
    const c = color(g);
    L.circle([g.lat, g.lon], { radius: g.radius_km * 1000, color: c, weight: 1.5, fillOpacity: 0.08 }).addTo(overlay);
    const size = i === 0 ? 30 : 24;
    const m = L.marker([g.lat, g.lon], { icon: L.divIcon({ className: "", iconSize: [size, size],
      html: `<div class="guess-pin" style="width:${size}px;height:${size}px;background:${c}">${i + 1}</div>` }),
      zIndexOffset: 1000 - i * 100 }).addTo(overlay);
    const n = placeName(g);
    m.bindPopup(`<b>#${i + 1} ${esc(n.main)}</b><br>${esc(n.sub)}<br>${pct(g.confidence)} confidence · ±${Math.round(g.radius_km)} km<br>
      <small>${g.lat.toFixed(4)}, ${g.lon.toFixed(4)}</small>`);
    m.on("click", () => { selected = i; renderGuesses(d); });
    // Frame only guesses that matter, so one stray low guess doesn't zoom out to the world.
    if (i === 0 || g.confidence >= 0.25 * d.guesses[0].confidence) pts.push([g.lat, g.lon]);
  });
  for (const a of d.analysts || []) {
    if (!a.ok) continue;
    const c = css(ANALYST[a.provider].color), letter = ANALYST[a.provider].letter;
    a.guesses.forEach((g, gi) => {
      const place = [g.place, g.country].filter(Boolean).join(", ");
      L.marker([g.lat, g.lon], { icon: L.divIcon({ className: "", iconSize: [24, 24],
        html: `<div class="llm-pin" style="background:${c};opacity:${gi ? 0.75 : 1}"><span>${letter}${gi ? gi + 1 : ""}</span></div>` }),
        zIndexOffset: 1500 - gi * 10 }).addTo(overlay)
        .bindPopup(`<b>${esc(a.name)} #${gi + 1}: ${esc(place)}</b><br>${pct(g.confidence)} sure · ±${Math.round(g.radius_km)} km<br>
          <small>${g.lat.toFixed(4)}, ${g.lon.toFixed(4)}</small>${gi === 0 ? `<br><small>${esc(a.reasoning.slice(0, 300))}</small>` : ""}`);
      if (gi === 0) pts.push([g.lat, g.lon]);
    });
  }
  if (d.exif_gps) {
    L.marker([d.exif_gps.lat, d.exif_gps.lon], { icon: L.divIcon({ className: "", html: `<div class="exif-pin" title="EXIF GPS">★</div>`, iconSize: [26, 26] }),
      zIndexOffset: 2000 }).bindPopup(`<b>EXIF GPS</b> (from the photo's metadata)<br>${d.exif_gps.lat.toFixed(5)}, ${d.exif_gps.lon.toFixed(5)}`)
      .addTo(overlay);
    pts.push([d.exif_gps.lat, d.exif_gps.lon]);
  }
  if (pts.length === 1) map.setView(pts[0], 6);
  else if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.4), { maxZoom: 6 });
}

function focusGuess(i) {
  const g = current.data.guesses[i];
  const z = g.radius_km < 30 ? 9 : g.radius_km < 100 ? 7 : g.radius_km < 300 ? 6 : 5;
  map.flyTo([g.lat, g.lon], z, { duration: 0.8 });
}

function renderHistory() {
  $("#history-wrap").hidden = history.length < 2;
  $("#history").innerHTML = "";
  history.forEach((h) => {
    const img = document.createElement("img");
    img.src = h.url; img.title = h.name;
    if (h === current) img.className = "sel";
    img.onclick = () => show(h);
    $("#history").appendChild(img);
  });
}
