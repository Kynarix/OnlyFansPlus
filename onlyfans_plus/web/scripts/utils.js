// ufak yardımcılar ve pywebview api köprüsü

function apiReady() {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve();
    window.addEventListener("pywebviewready", () => resolve(), { once: true });
  });
}

async function call(fn, ...args) {
  await apiReady();
  try { return await window.pywebview.api[fn](...args); }
  catch (e) { console.error("api hatası", fn, e); throw e; }
}

const $ = (id) => document.getElementById(id);
const el = (tag, cls) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
};

const escapeHtml = (s) => (s || "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]
));

function fmtBytes(n) {
  if (!n || n <= 0) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let f = n;
  for (const x of u) {
    if (f < 1024) return (x === "B" ? Math.floor(f) : f.toFixed(1)) + " " + x;
    f /= 1024;
  }
  return f.toFixed(1) + " PB";
}

const fmtSpeed = (bps) => (!bps || bps <= 0) ? "—/s" : fmtBytes(bps) + "/s";

function fmtEta(sec) {
  if (!sec || sec < 0 || !isFinite(sec)) return "—";
  const s = Math.round(sec);
  const m = Math.floor(s / 60), r = s % 60;
  if (m >= 60) { const h = Math.floor(m / 60), mm = m % 60; return `${h}sa ${mm}dk`; }
  return m > 0 ? `${m}dk ${r}sn` : `${r}sn`;
}
