// başlatma — api hazır olunca ilk sayfayı ve verileri yükler

(async () => {
  await apiReady();
  setPage("search");
  loadSettings();
  loadState();
  // aktif liste placeholder
  const list = $("active-list");
  const e = el("div", "active-empty");
  e.textContent = "Aktif indirme yok.";
  list.appendChild(e);
})();
