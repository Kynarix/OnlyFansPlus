// ayarlar sayfası

async function loadSettings() {
  try {
    const s = await call("get_settings");
    $("set-root").value = s.download_root || "";
    $("set-workers").value = s.max_workers || 4;
    $("set-delay").value = s.delay ?? 0.4;
    $("set-images").checked = !!s.filter_images;
    $("set-videos").checked = !!s.filter_videos;
  } catch (e) { console.error("ayar yükleme", e); }
}

$("set-browse").addEventListener("click", async () => {
  const p = await call("pick_folder");
  if (p) $("set-root").value = p;
});

$("set-save").addEventListener("click", async () => {
  await call("save_settings",
    $("set-root").value,
    Number($("set-workers").value) || 4,
    Number($("set-delay").value) || 0,
    $("set-images").checked,
    $("set-videos").checked);
  const msg = $("set-saved");
  msg.classList.remove("hidden");
  setTimeout(() => msg.classList.add("hidden"), 1800);
});
