// içerik sayfası: creator seç, postları canlı yükle, önizleme

async function selectCreator(c) {
  state.selectedCreator = c;
  state.posts = [];
  state.selected.clear();
  $("cc-avatar").src = c.avatar;
  $("cc-name").textContent = c.name;
  $("cc-service").textContent = c.service;
  $("cc-count-num").textContent = "0";
  $("select-all").checked = false;
  $("posts-grid").innerHTML = "";
  $("content-empty").classList.add("hidden");
  $("content-body").classList.add("hidden");
  // yükleme ekranını göster
  $("content-loader").classList.remove("hidden");
  $("loader-sub").textContent = "Hazırlanıyor";
  $("loader-bar-fill").style.width = "4%";
  $("loader-bar-fill").classList.add("indeterminate");
  setPage("content");
  await call("load_all_posts", c.key);
}

// backend -> UI: post batch'i geldi
window.__postsBatch = function (payload) {
  const grid = $("posts-grid");
  payload.items.forEach((p) => {
    state.posts.push(p);
    grid.appendChild(buildPostCard(p));
  });
  $("cc-count-num").textContent = payload.running;
  $("loader-sub").textContent = `${payload.running} gönderi bulundu`;
  // toplam sayfa bilinmediği için sahte ilerleme
  $("loader-bar-fill").style.width = Math.min(92, 8 + payload.running * 1.5) + "%";
};

window.__postsDone = function (total) {
  $("cc-count-num").textContent = total;
  $("loader-bar-fill").style.width = "100%";
  // kısa bir geçiş, sonra içeriği göster
  setTimeout(() => {
    $("content-loader").classList.add("hidden");
    $("content-body").classList.remove("hidden");
  }, 350);
};

window.__postsError = function (msg) {
  $("content-loader").classList.add("hidden");
  $("content-body").classList.remove("hidden");
  console.error("post hatası", msg);
};

function buildPostCard(p) {
  const card = el("div", "post-card");
  card.dataset.index = p.index;
  const thumb = p.thumb
    ? `<img src="${escapeHtml(p.thumb)}" alt="" loading="lazy" onerror="this.parentNode.classList.add('no-thumb');this.remove();"/>`
    : `<span class="material-icons-outlined">image</span>`;
  card.innerHTML = `
    <div class="post-thumb ${p.thumb ? "" : "no-thumb"}" data-index="${p.index}">
      <input type="checkbox" class="post-check" data-index="${p.index}"/>
      ${thumb}
    </div>
    <div class="post-body">
      <div class="post-title" title="${escapeHtml(p.title)}">${escapeHtml(p.title)}</div>
      <div class="post-foot">
        <span class="post-date"><span class="material-icons-outlined">calendar_today</span>${escapeHtml(p.date || "—")}</span>
        <span class="badge none"><span class="material-icons-outlined">visibility</span>önizle</span>
      </div>
    </div>`;
  // thumb'a tıkla -> önizle
  card.querySelector(".post-thumb").addEventListener("click", (e) => {
    if (e.target.classList.contains("post-check")) return;
    openPreview(p.index);
  });
  const cb = card.querySelector(".post-check");
  cb.addEventListener("click", (e) => e.stopPropagation());
  cb.addEventListener("change", (e) => {
    const idx = Number(e.target.dataset.index);
    if (e.target.checked) { state.selected.add(idx); card.classList.add("selected"); }
    else { state.selected.delete(idx); card.classList.remove("selected"); }
  });
  return card;
}

// tümünü seç
$("select-all").addEventListener("change", (e) => {
  const checked = e.target.checked;
  state.selected.clear();
  document.querySelectorAll(".post-card").forEach((card) => {
    const cb = card.querySelector(".post-check");
    cb.checked = checked;
    if (checked) { state.selected.add(Number(card.dataset.index)); card.classList.add("selected"); }
    else { card.classList.remove("selected"); }
  });
});

// seçilenleri indir
$("download-all-btn").addEventListener("click", async () => {
  const indices = Array.from(state.selected);
  const list = indices.length ? indices : state.posts.map((p) => p.index);
  if (!list.length) return;
  setPage("downloads");
  resetDownloadUI();
  await call("start_download", list);
});

// --- önizleme modalı ---
async function openPreview(index) {
  $("pv-grid").innerHTML = `<div class="spinner" style="margin:40px auto;"></div>`;
  $("pv-title").textContent = "Yükleniyor…";
  $("pv-meta").textContent = "";
  $("pv-img-count").textContent = "0";
  $("pv-vid-count").textContent = "0";
  $("preview-modal").classList.remove("hidden");
  try {
    const m = await call("get_post_media", index);
    if (!m.ok) {
      $("pv-title").textContent = "Hata";
      $("pv-meta").textContent = m.error || "";
      $("pv-grid").innerHTML = "";
      return;
    }
    $("pv-title").textContent = m.title || "(başlıksız)";
    $("pv-meta").textContent = m.date || "";
    $("pv-img-count").textContent = m.images.length;
    $("pv-vid-count").textContent = m.videos.length;
    renderPreviewGrid(m.images, m.videos);
  } catch (e) {
    $("pv-title").textContent = "Hata";
    $("pv-grid").innerHTML = "";
  }
}

function renderPreviewGrid(images, videos) {
  const grid = $("pv-grid");
  grid.innerHTML = "";
  images.forEach((u) => {
    const c = el("div", "pv-cell");
    c.innerHTML = `<img src="${escapeHtml(u)}" loading="lazy" onerror="this.parentNode.classList.add('no-thumb');this.remove()"/>`;
    grid.appendChild(c);
  });
  videos.forEach((u) => {
    const c = el("div", "pv-cell");
    c.innerHTML = `<video src="${escapeHtml(u)}" controls preload="metadata"></video>`;
    grid.appendChild(c);
  });
}

$("pv-close").addEventListener("click", () => $("preview-modal").classList.add("hidden"));
document.querySelector(".modal-backdrop").addEventListener("click", () =>
  $("preview-modal").classList.add("hidden"));
