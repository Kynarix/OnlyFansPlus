// global durum ve sayfa geçişleri

const state = {
  selectedCreator: null,   // { key, name, service, id, avatar }
  posts: [],               // backend'den gelen postlar burada birikir
  selected: new Set(),     // seçili post index'leri
  favorites: new Set(),    // favori creator key'leri
  dl: { active: {}, speeds: {}, done: 0, total: 0, failed: 0, finished: false, prep: false },
};

const PAGE_META = {
  search:    { title: "Arama",      sub: "Bir içerik üreticisi ara." },
  content:   { title: "İçerik",     sub: "Gönderileri önizle ve seç." },
  downloads: { title: "İndirmeler", sub: "İndirme kuyruğu, canlı ilerleme ve loglar." },
  settings:  { title: "Ayarlar",    sub: "İndirme tercihlerini yönet." },
};

function setPage(name) {
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.page === name));
  document.querySelectorAll(".page").forEach((p) => p.classList.add("hidden"));
  const page = $("page-" + name);
  page.classList.remove("hidden");
  // sayfa geçiş animasyonunu tazele
  page.style.animation = "none"; void page.offsetHeight; page.style.animation = "";
  $("page-title").textContent = PAGE_META[name].title;
  $("page-sub").textContent = PAGE_META[name].sub;
}

document.querySelectorAll(".nav-item").forEach((b) =>
  b.addEventListener("click", () => setPage(b.dataset.page)));
