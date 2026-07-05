// indirmeler: canlı ilerleme, hazırlık fazı, loglar

function resetDownloadUI() {
  state.dl = { active: {}, speeds: {}, done: 0, total: 0, failed: 0, finished: false, prep: true };
  $("dl-status").textContent = "Hazırlanıyor…";
  $("dl-cancel").disabled = false;
  $("overall-fill").style.width = "0%";
  $("overall-text").textContent = "0%";
  $("active-list").innerHTML = "";
  $("dl-log").innerHTML = "";
  refreshDlStats();
}

// hazırlık fazı durum mesajları (medya çekme / paketleme)
window.__dlStage = function (phase, i, n, total, eta) {
  if (phase === "start") {
    state.dl.prep = true;
    $("dl-status").textContent = "Hazırlanıyor…";
    $("overall-text").textContent = "hazırlık";
    $("overall-fill").style.width = "2%";
  } else if (phase === "fetch") {
    state.dl.prep = true;
    const pct = n > 0 ? Math.round((i / n) * 100) : 0;
    $("overall-fill").style.width = pct + "%";
    $("overall-text").textContent = "hazırlık " + pct + "%";
    $("dl-status").innerHTML =
      `Kaynaklar çekiliyor… <b>${i}/${n}</b> gönderi · kuyruk: <b>${total}</b> dosya · <span class="muted">~${fmtEta(eta)}</span>`;
  } else if (phase === "ready") {
    $("overall-fill").style.width = "100%";
    $("overall-text").textContent = "hazır";
    $("dl-status").innerHTML = `Paketleniyor… <b>${total}</b> dosya kuyrukta, indirme başlıyor.`;
  } else if (phase === "queue") {
    const pct = n > 0 ? Math.round((i / n) * 100) : 0;
    $("overall-fill").style.width = pct + "%";
    $("overall-text").textContent = "paketleme " + pct + "%";
    $("dl-status").innerHTML = `Paketleniyor… <b>${i}/${n}</b> · kuyruk: <b>${total}</b> dosya`;
  } else if (phase === "empty") {
    state.dl.prep = false;
    $("dl-status").textContent = "İndirilecek dosya bulunamadı.";
    $("overall-text").textContent = "—";
    $("dl-cancel").disabled = true;
  }
};

function logLine(msg, cls) {
  const div = el("div", cls || "");
  div.textContent = msg;
  const box = $("dl-log");
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

window.__dlLog = function (msg) { logLine(msg, classifyLog(msg)); };

window.__dlOverall = function (done, total) {
  state.dl.done = done; state.dl.total = total; state.dl.prep = false;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  $("overall-fill").style.width = pct + "%";
  $("overall-text").textContent = pct + "%";
  $("dl-status").textContent = `İndiriliyor  ${done}/${total}`;
  refreshDlStats();
};

window.__dlStart = function (key, kind, name) {
  state.dl.active[key] = { kind, name, received: 0, total: 0 };
  const row = el("div", "active-row");
  row.dataset.key = key;
  row.innerHTML = `
    <div class="ar-top">
      <span class="material-icons-outlined" style="font-size:15px;color:var(--accent)">${kind === "video" ? "videocam" : "image"}</span>
      <span class="ar-name">${escapeHtml(name)}</span>
      <span class="ar-stats">bekleniyor…</span>
    </div>
    <div class="ar-bar"><div class="ar-fill"></div></div>`;
  const list = $("active-list");
  const empty = list.querySelector(".active-empty"); if (empty) empty.remove();
  list.appendChild(row);
};

window.__dlBytes = function (key, received, total, speed) {
  const a = state.dl.active[key]; if (!a) return;
  a.received = received; a.total = total; state.dl.speeds[key] = speed;
  const row = $("active-list").querySelector(`.active-row[data-key="${CSS.escape(key)}"]`);
  if (row) {
    const fill = row.querySelector(".ar-fill");
    fill.style.width = total > 0 ? Math.min(100, (received / total) * 100) + "%" : "90%";
    row.querySelector(".ar-stats").textContent = `${fmtBytes(received)} / ${fmtBytes(total)} · ${fmtSpeed(speed)}`;
  }
};

window.__dlDone = function (key, ok) {
  delete state.dl.active[key]; delete state.dl.speeds[key];
  if (!ok) state.dl.failed++;
  const row = $("active-list").querySelector(`.active-row[data-key="${CSS.escape(key)}"]`);
  if (row) {
    row.style.transition = "opacity .3s ease"; row.style.opacity = "0";
    setTimeout(() => row.remove(), 300);
  }
  if (Object.keys(state.dl.active).length === 0) {
    const list = $("active-list");
    if (!list.querySelector(".active-empty")) {
      const e = el("div", "active-empty"); e.textContent = "Aktif indirme yok.";
      list.appendChild(e);
    }
  }
  refreshDlStats();
};

window.__dlFinished = function () {
  state.dl.finished = true;
  $("dl-status").textContent = "Tamamlandı ✓";
  $("dl-cancel").disabled = true;
  $("overall-fill").style.width = "100%";
  $("overall-text").textContent = "100%";
  $("dl-stats").textContent = `${state.dl.done} / ${state.dl.total} dosya · 0 aktif · Hata: ${state.dl.failed} · —/s`;
};

function classifyLog(msg) {
  if (msg.includes("[✓]")) return "line-ok";
  if (msg.includes("[✗]")) return "line-err";
  if (msg.includes("[!]") || msg.includes("[↻]")) return "line-warn";
  return "";
}

function refreshDlStats() {
  if (state.dl.prep && state.dl.total === 0) {
    $("dl-stats").textContent = "Kaynaklar hazırlanıyor…";
    return;
  }
  const active = Object.keys(state.dl.active).length;
  const agg = Object.values(state.dl.speeds).reduce((a, b) => a + (b || 0), 0);
  $("dl-stats").textContent =
    `${state.dl.done} / ${state.dl.total} dosya · ${active} aktif · Hata: ${state.dl.failed} · ${fmtSpeed(agg)}`;
}

// periyodik hız tazeleme
setInterval(() => { if (!state.dl.finished) refreshDlStats(); }, 400);

$("dl-cancel").addEventListener("click", async () => {
  $("dl-status").textContent = "İptal ediliyor…";
  $("dl-cancel").disabled = true;
  await call("cancel_download");
});
