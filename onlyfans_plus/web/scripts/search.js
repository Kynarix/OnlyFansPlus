// arama, favoriler ve geçmiş aramalar

async function doSearch() {
  const q = $("search-input").value.trim();
  if (!q) return;
  $("search-btn").disabled = true;
  $("search-results").innerHTML = "";
  $("search-empty").classList.add("hidden");
  $("results-section").classList.add("hidden");
  $("search-hint").textContent = "Aranıyor…";
  try {
    const results = await call("search", q);
    $("search-hint").textContent = results.length ? `${results.length} sonuç bulundu` : "Sonuç yok.";
    if (results.length) {
      $("results-count").textContent = `(${results.length})`;
      $("results-section").classList.remove("hidden");
    }
    renderSearchResults(results);
  } catch (e) {
    $("search-hint").textContent = "Arama hatası.";
  } finally {
    $("search-btn").disabled = false;
  }
}

function renderSearchResults(list) {
  const grid = $("search-results");
  if (!list.length) { $("search-empty").classList.remove("hidden"); return; }
  list.forEach((c, i) => {
    const card = el("div", "creator-result");
    card.style.animationDelay = (i * 40) + "ms";
    const isFav = state.favorites.has(c.key);
    card.innerHTML = `
      <img class="avatar" src="${escapeHtml(c.avatar)}" alt="" onerror="this.style.visibility='hidden'"/>
      <div class="creator-info">
        <div class="name">${escapeHtml(c.name)}</div>
        <div class="sub"><span class="pill">${escapeHtml(c.service)}</span><span>#${escapeHtml(c.id)}</span></div>
      </div>
      <button class="select-btn" data-key="${escapeHtml(c.key)}">Seç</button>
      <button class="fav-toggle ${isFav ? "active" : ""}" data-key="${escapeHtml(c.key)}" title="Favori">
        <span class="material-icons-outlined">${isFav ? "favorite" : "favorite_border"}</span>
      </button>`;
    grid.appendChild(card);
  });
  grid.querySelectorAll(".select-btn").forEach((b) => b.addEventListener("click", (e) => {
    const c = list.find((x) => x.key === e.target.dataset.key);
    selectCreator(c);
  }));
  grid.querySelectorAll(".fav-toggle").forEach((b) => b.addEventListener("click", async (e) => {
    e.stopPropagation();
    const c = list.find((x) => x.key === b.dataset.key);
    const res = await call("toggle_favorite", c.key, c.name, c.service, c.id, c.avatar);
    applyFavorites(res.favorites);
    b.classList.toggle("active", res.isFavorite);
    b.querySelector(".material-icons-outlined").textContent = res.isFavorite ? "favorite" : "favorite_border";
  }));
}

$("search-btn").addEventListener("click", doSearch);
$("search-input").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });

// --- favoriler ---
function applyFavorites(favs) {
  state.favorites = new Set((favs || []).map((f) => f.key));
  renderFavorites(favs || []);
  // ekrandaki favori butonlarını da güncelle
  document.querySelectorAll(".fav-toggle").forEach((b) => {
    const active = state.favorites.has(b.dataset.key);
    b.classList.toggle("active", active);
    const ico = b.querySelector(".material-icons-outlined");
    if (ico) ico.textContent = active ? "favorite" : "favorite_border";
  });
}

function renderFavorites(favs) {
  const sec = $("favorites-section");
  const grid = $("favorites-grid");
  grid.innerHTML = "";
  if (!favs || !favs.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  favs.forEach((f) => {
    const card = el("div", "fav-card");
    card.innerHTML = `
      <img class="avatar" src="${escapeHtml(f.avatar)}" alt="" onerror="this.style.visibility='hidden'"/>
      <div class="finfo">
        <div class="fname">${escapeHtml(f.name)}</div>
        <div class="fsub"><span class="pill" style="font-size:10px">${escapeHtml(f.service)}</span><span>#${escapeHtml(f.id)}</span></div>
      </div>
      <button class="fopen" data-key="${escapeHtml(f.key)}">Aç</button>
      <button class="funfav" title="Favoriden çıkar"><span class="material-icons-outlined">close</span></button>`;
    card.querySelector(".fopen").addEventListener("click", () => selectCreator(f));
    card.querySelector(".funfav").addEventListener("click", async () => {
      const res = await call("remove_favorite", f.key);
      applyFavorites(res.favorites);
    });
    grid.appendChild(card);
  });
}

// --- geçmiş ---
function renderHistory(history) {
  const sec = $("history-section");
  const row = $("history-chips");
  row.innerHTML = "";
  if (!history || !history.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  history.forEach((q) => {
    const chip = el("div", "history-chip");
    chip.innerHTML = `<span>${escapeHtml(q)}</span><button class="rm" title="Kaldır">×</button>`;
    chip.addEventListener("click", (e) => {
      if (e.target.classList.contains("rm")) return;
      $("search-input").value = q;
      doSearch();
    });
    chip.querySelector(".rm").addEventListener("click", async (e) => {
      e.stopPropagation();
      // teke tek silme yok, kalan listeyi yeniden ekleyerek yap
      const remaining = history.filter((h) => h !== q);
      await call("clear_history");
      for (let i = remaining.length - 1; i >= 0; i--) await call("add_history", remaining[i]);
      const st = await call("get_state");
      renderHistory(st.history);
    });
    row.appendChild(chip);
  });
}

async function loadState() {
  try {
    const st = await call("get_state");
    applyFavorites(st.favorites);
    renderHistory(st.history);
  } catch (e) { console.error("state yükleme", e); }
}

// arama sonrası backend geçmiş'i güncelledi, UI tazele
window.__historyUpdated = function () {
  call("get_state").then((st) => renderHistory(st.history)).catch(() => {});
};

$("clear-history").addEventListener("click", async () => {
  await call("clear_history");
  renderHistory([]);
});

// --- sidebar: discord kopyala ---
$("discord-link").addEventListener("click", async () => {
  const btn = $("discord-link");
  try {
    await navigator.clipboard.writeText("phexora");
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = "phexora"; document.body.appendChild(ta);
    ta.select(); try { document.execCommand("copy"); } catch (_) {} ta.remove();
  }
  btn.classList.add("copied");
  const span = btn.querySelector("span");
  const orig = span.textContent;
  span.textContent = "phexora — kopyalandı!";
  setTimeout(() => { btn.classList.remove("copied"); span.textContent = orig; }, 1400);
});

window.__searchError = function (msg) { $("search-hint").textContent = "Hata: " + msg; };
