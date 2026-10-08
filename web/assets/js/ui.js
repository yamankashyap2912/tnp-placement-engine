// Shared building blocks: element helper, icons, formatting, chips, tables, charts, modal, toast.
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k.startsWith("aria-") && typeof v === "boolean") { el.setAttribute(k, String(v)); continue; }
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

// ------------------------------------------------------------------ icons (24px, stroke)
const P = {
  home: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/><rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="13" width="7" height="7" rx="2"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r=".8" fill="currentColor"/>',
  users: '<circle cx="9" cy="8.5" r="3.2"/><path d="M3 19c.5-3.4 3-5 6-5s5.5 1.6 6 5"/><path d="M16 5.6a3 3 0 0 1 0 5.8M18 14.4c1.9.6 3 2.2 3.2 4.6"/>',
  user: '<circle cx="12" cy="8.5" r="3.6"/><path d="M4.5 20c.7-4 3.7-6 7.5-6s6.8 2 7.5 6"/>',
  briefcase: '<rect x="3.5" y="7.5" width="17" height="12" rx="3"/><path d="M9 7.5V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1.5M3.5 13h17"/>',
  bell: '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z"/><path d="M10 21h4"/>',
  flow: '<circle cx="6" cy="6" r="2.4"/><circle cx="18" cy="12" r="2.4"/><circle cx="6" cy="18" r="2.4"/><path d="M8.2 7.2 15.8 11M8.2 16.8 15.8 13"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  database: '<ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6M4.5 12v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6"/>',
  chat: '<path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 3.5V16h0A2.5 2.5 0 0 1 4 13.5z"/><path d="M8.5 9.5h7M8.5 12.5h4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  up: '<path d="M7 17 17 7M8.5 7H17v8.5"/>',
  right: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  pin: '<path d="M12 21s6.5-5.6 6.5-11a6.5 6.5 0 0 0-13 0c0 5.4 6.5 11 6.5 11z"/><circle cx="12" cy="10" r="2.4"/>',
  building: '<rect x="5" y="3.5" width="14" height="17" rx="2.5"/><path d="M9 8h2M13 8h2M9 12h2M13 12h2M10 20.5v-4h4v4"/>',
  calendar: '<rect x="4" y="5.5" width="16" height="14.5" rx="3"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
  coin: '<circle cx="12" cy="12" r="8.5"/><path d="M9 8.5h6M9 11.5h6M10 8.5c4 0 4 5 0 5l4.5 3.5"/>',
  heart: '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z"/>',
  bookmark: '<path d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z"/>',
  share: '<circle cx="6" cy="12" r="2.4"/><circle cx="18" cy="6" r="2.4"/><circle cx="18" cy="18" r="2.4"/><path d="m8.2 10.8 7.6-3.6M8.2 13.2l7.6 3.6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.2-4.5L4 8.5M4 4v4.5h4.5M4 13a8 8 0 0 0 14.2 4.5l1.8-2M20 20v-4.5h-4.5"/>',
  download: '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  alert: '<path d="M12 4 3 19.5h18z"/><path d="M12 10v4.5M12 17.2v.1"/>',
  spark: '<path d="M12 3l1.8 5.4L19 10l-5.2 1.6L12 17l-1.8-5.4L5 10l5.2-1.6zM18.5 16l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
  list: '<path d="M8 6.5h12M8 12h12M8 17.5h12M4 6.5h.01M4 12h.01M4 17.5h.01"/>',
  logout: '<path d="M14 4h4.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H14M10 8l-4 4 4 4M6 12h10"/>',
  play: '<path d="M8 5.5v13l11-6.5z"/>',
  tag: '<path d="M4 12.5V5h7.5l8 8-7.5 7.5z"/><circle cx="8.5" cy="9" r="1.2" fill="currentColor"/>',
  lock: '<rect x="5" y="10.5" width="14" height="9.5" rx="2.5"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
};
export function icon(name, size = 20) {
  const s = h("span", { class: "ico", "aria-hidden": "true", style: { display: "inline-grid", width: size + "px", height: size + "px" } });
  s.innerHTML = `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${P[name] || ""}</svg>`;
  return s;
}

// ------------------------------------------------------------------ formatting
export const fmt = {
  n: (v, d = 0) => (v === null || v === undefined || Number.isNaN(+v) ? "-" : (+v).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d })),
  pct: (v, d = 0) => (v === null || v === undefined ? "-" : `${(+v * 100).toFixed(d)}%`),
  ctc: (v) => (v === null || v === undefined ? "-" : `${(+v).toFixed(+v % 1 ? 1 : 0)} LPA`),
  score: (v) => (v === null || v === undefined ? "-" : (+v).toFixed(2)),
  date: (s) => (s ? String(s).slice(0, 10) : "-"),
  short: (v) => (v >= 1000 ? `${Math.floor(v / 1000)}K+` : String(v)),
  initials: (name = "") => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase(),
};

// ------------------------------------------------------------------ chips
const STATUS = { SELECTED: "ok", PLACED: "ok", REJECTED: "bad", NOT_PLACED: "mute", IN_PROGRESS: "warn", APPLIED: "", WITHDRAWN: "mute", IN_PROCESS: "warn",
  OPEN: "ok", CLOSED: "mute", PASS: "ok", REJECT: "bad", SELECT: "ok", PENDING: "warn", PASS_: "ok" };
const label = (s) => String(s).replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
export const chip = (text, kind = "") => h("span", { class: `chip ${kind}` }, text);
export const statusChip = (s) => (s ? chip(label(s), STATUS[s] ?? "") : chip("-", "mute"));
export const bandChip = (b) => chip(label(b || "unknown"), { STRONG: "ok", GOOD: "", FAIR: "warn", WEAK: "bad" }[b] ?? "mute");
export const riskChip = (b) => chip(label(b), { CRITICAL: "bad", HIGH: "warn", MODERATE: "" }[b] ?? "mute");

export function scoreBar(v, { max = 1, asPct = false } = {}) {
  const pct = Math.max(0, Math.min(1, (v ?? 0) / max));
  const cls = pct >= 0.75 ? "hi" : pct < 0.4 ? "lo" : "";
  const text = asPct ? (v === null || v === undefined ? "-" : `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%`) : fmt.score(v);
  return h("span", { class: "scorebar" }, h("span", { class: "track" }, h("span", { class: `fill ${cls}`, style: { width: `${Math.max(pct * 100, v ? 2 : 0)}%` } })), h("b", { class: "num" }, text));
}

export function dots(level, need = 0) {
  return h("span", { class: "dots", title: `Level ${level}${need ? ` of ${need} needed` : ""}` },
    [1, 2, 3, 4, 5].map((i) => h("i", { class: `${i <= level ? "on" : ""} ${i === need ? "need" : ""}` })));
}

// ------------------------------------------------------------------ table
export function table({ columns, rows, onRow, empty = "Nothing to show yet.", sub }) {
  if (!rows || !rows.length) return h("div", { class: "empty" }, h("b", {}, empty), sub || "");
  const tbody = h("tbody", {}, rows.map((r, i) => {
    const tr = h("tr", { class: onRow ? "click" : "", tabindex: onRow ? "0" : undefined,
      onclick: onRow ? () => onRow(r) : undefined,
      onkeydown: onRow ? (e) => { if (e.key === "Enter") onRow(r); } : undefined },
    columns.map((c) => h("td", { class: c.align === "right" ? "r" : "" }, c.render ? c.render(r, i) : (r[c.key] ?? "-"))));
    return tr;
  }));
  return h("div", { class: "tbl-wrap" }, h("table", { class: "tbl" },
    h("thead", {}, h("tr", {}, columns.map((c) => h("th", { class: c.align === "right" ? "r" : "" }, c.label)))), tbody));
}

export const skeleton = (n = 4) => h("div", { class: "grid" }, Array.from({ length: n }, () => h("div", { class: "skeleton", style: { height: "34px" } })));

// ------------------------------------------------------------------ charts (inline SVG, theme-aware)
const NS = "http://www.w3.org/2000/svg";
const svg = (w, hgt) => { const s = document.createElementNS(NS, "svg"); s.setAttribute("viewBox", `0 0 ${w} ${hgt}`); s.setAttribute("class", "chart"); s.setAttribute("role", "img"); return s; };
const sn = (tag, attrs = {}, text) => { const e = document.createElementNS(NS, tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); if (text !== undefined) e.textContent = text; return e; };
export const PALETTE = ["#5b4fe6", "#35b88a", "#e9a23b", "#e0607e", "#4aa3df", "#9a7be0"];

export function barChart(data, { height = 190, color = PALETTE[0], format = (v) => fmt.n(v), colors, aria = "Bar chart" } = {}) {
  const W = 520, padL = 8, padB = 28, padT = 20, hgt = height;
  const s = svg(W, hgt); s.setAttribute("aria-label", aria);
  const max = Math.max(...data.map((d) => d.value), 1);
  const bw = (W - padL * 2) / data.length;
  [0.5, 1].forEach((f) => s.append(sn("line", { class: "grid-line", x1: padL, x2: W - padL, y1: padT + (hgt - padT - padB) * (1 - f), y2: padT + (hgt - padT - padB) * (1 - f) })));
  data.forEach((d, i) => {
    const bh = ((hgt - padT - padB) * d.value) / max;
    const x = padL + i * bw + bw * 0.16, w = bw * 0.68, y = hgt - padB - bh;
    s.append(sn("rect", { x, y, width: w, height: Math.max(bh, 1), rx: Math.min(10, w / 2), fill: (colors && colors[i]) || color, opacity: ".92" }));
    s.append(sn("text", { x: x + w / 2, y: y - 6, "text-anchor": "middle" }, format(d.value)));
    s.append(sn("text", { x: x + w / 2, y: hgt - 9, "text-anchor": "middle" }, d.label));
  });
  s.append(sn("line", { class: "axis", x1: padL, x2: W - padL, y1: hgt - padB, y2: hgt - padB }));
  return s;
}

export function hbars(data, { format = (v) => fmt.n(v), max, color } = {}) {
  const m = max ?? Math.max(...data.map((d) => d.value), 1);
  return h("div", {}, data.map((d) => h("div", { class: "hbar" },
    h("span", { class: "name", title: d.label }, d.label),
    h("span", { class: "track" }, h("span", { class: "fill", style: { width: `${Math.max(2, (d.value / m) * 100)}%`, ...(color ? { background: color } : {}) } })),
    h("span", { class: "val num" }, format(d.value)))));
}

export function ring(value, { size = 150, stroke = 14, label = "", color } = {}) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, v = Math.max(0, Math.min(1, value ?? 0));
  const col = color || (v >= 0.6 ? "#1b9a69" : v >= 0.3 ? "#d68a1a" : "#d2495a");
  const s = svg(size, size); s.style.width = size + "px"; s.style.height = size + "px"; s.setAttribute("aria-label", `${label}: ${Math.round(v * 100)}%`);
  s.append(sn("circle", { cx: size / 2, cy: size / 2, r, fill: "none", stroke: "rgba(110,108,170,.18)", "stroke-width": stroke }));
  const arc = sn("circle", { cx: size / 2, cy: size / 2, r, fill: "none", stroke: col, "stroke-width": stroke, "stroke-linecap": "round",
    "stroke-dasharray": `${c * v} ${c}`, transform: `rotate(-90 ${size / 2} ${size / 2})` });
  s.append(arc);
  return h("div", { class: "ring", style: { width: size + "px", height: size + "px" } }, s,
    h("div", { class: "center" }, h("b", { class: "num", style: { fontSize: `${Math.round(size * 0.24)}px` } }, `${Math.round(v * 100)}%`), h("small", {}, label)));
}

export function linePlot(series, { height = 230, xLabel = "", yLabel = "", diagonal = false } = {}) {
  const W = 520, padL = 40, padR = 12, padT = 12, padB = 38, hgt = height;
  const s = svg(W, hgt); s.setAttribute("aria-label", "Line chart");
  const X = (v) => padL + v * (W - padL - padR), Y = (v) => padT + (1 - v) * (hgt - padT - padB);
  [0, 0.25, 0.5, 0.75, 1].forEach((t) => {
    s.append(sn("line", { class: "grid-line", x1: padL, x2: W - padR, y1: Y(t), y2: Y(t) }));
    s.append(sn("text", { x: padL - 8, y: Y(t) + 4, "text-anchor": "end" }, `${t * 100}%`));
    s.append(sn("text", { x: X(t), y: hgt - padB + 16, "text-anchor": "middle" }, `${t * 100}%`));
  });
  if (diagonal) s.append(sn("line", { x1: X(0), y1: Y(0), x2: X(1), y2: Y(1), stroke: "rgba(110,108,170,.5)", "stroke-dasharray": "5 5" }));
  series.forEach((ser, k) => {
    const col = ser.color || PALETTE[k];
    s.append(sn("polyline", { points: ser.points.map(([x, y]) => `${X(x)},${Y(y)}`).join(" "), fill: "none", stroke: col, "stroke-width": 2.5, "stroke-linejoin": "round" }));
    ser.points.forEach(([x, y]) => s.append(sn("circle", { cx: X(x), cy: Y(y), r: 3.8, fill: col })));
  });
  s.append(sn("text", { x: W / 2, y: hgt - 4, "text-anchor": "middle" }, xLabel));
  s.append(sn("text", { x: 11, y: hgt / 2, "text-anchor": "middle", transform: `rotate(-90 11 ${hgt / 2})` }, yLabel));
  return s;
}

export function radar(labels, series, { size = 300, max = 5 } = {}) {
  const s = svg(size, size); s.setAttribute("aria-label", "Skill radar");
  const cx = size / 2, cy = size / 2, R = size / 2 - 52, n = labels.length;
  const pt = (i, v) => { const a = (Math.PI * 2 * i) / n - Math.PI / 2; return [cx + Math.cos(a) * R * (v / max), cy + Math.sin(a) * R * (v / max)]; };
  for (let g = 1; g <= max; g++) s.append(sn("polygon", { points: labels.map((_, i) => pt(i, g).join(",")).join(" "), fill: "none", stroke: "rgba(110,108,170,.22)" }));
  labels.forEach((l, i) => {
    const [x, y] = pt(i, max + 0.35);
    s.append(sn("line", { x1: cx, y1: cy, x2: pt(i, max)[0], y2: pt(i, max)[1], stroke: "rgba(110,108,170,.22)" }));
    s.append(sn("text", { x, y: y + 3, "text-anchor": x < cx - 6 ? "end" : x > cx + 6 ? "start" : "middle" }, l.length > 13 ? l.slice(0, 12) + "..." : l));
  });
  series.forEach((ser, k) => {
    const col = ser.color || PALETTE[k];
    s.append(sn("polygon", { points: ser.values.map((v, i) => pt(i, v).join(",")).join(" "), fill: col, "fill-opacity": ".18", stroke: col, "stroke-width": 2.2, "stroke-linejoin": "round" }));
  });
  return s;
}

export function legend(items) {
  return h("div", { class: "legend" }, items.map((i) => h("span", {}, h("i", { style: { background: i.color } }), i.label)));
}

// ------------------------------------------------------------------ feedback
export function toast(msg, kind = "") {
  const t = h("div", { class: `toast ${kind}`, role: "status" }, msg);
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), kind === "bad" ? 6500 : 3600);
}

export function modal(title, body, { wide = false } = {}) {
  const frame = document.getElementById("frame");
  const prevFocus = document.activeElement;
  const close = () => { back.remove(); document.removeEventListener("keydown", onKey); prevFocus?.focus?.(); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const back = h("div", { class: "modal-back", onclick: (e) => { if (e.target === back) close(); } },
    h("div", { class: `modal ${wide ? "wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title },
      h("button", { class: "pill-btn close", "aria-label": "Close", onclick: close }, icon("close", 20)),
      h("h2", {}, title), h("div", { style: { marginTop: "16px" } }, body)));
  frame.append(back);
  document.addEventListener("keydown", onKey);
  back.querySelector(".close").focus();
  return close;
}

export async function busy(btn, fn) {
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = ""; btn.append(h("span", { class: "spin" }), " Working");
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = old; }
}

export function downloadCsv(name, columns, rows) {
  const esc = (v) => { const s = v === null || v === undefined ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const csv = [columns.map((c) => esc(c.label)).join(","), ...rows.map((r) => columns.map((c) => esc(c.csv ? c.csv(r) : r[c.key])).join(","))].join("\n");
  const a = h("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: name });
  document.body.append(a); a.click(); a.remove();
}

export const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
