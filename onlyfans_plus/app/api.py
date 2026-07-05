"""JS'e açık backend. pywebview bu sınıfın metodlarını çağırır."""

from __future__ import annotations

import json
import os
import threading
import time
import webview

from onlyfans_plus.app import config
from onlyfans_plus.core.scraper import Scraper, Creator, Post, ScraperCancelled
from onlyfans_plus.core.downloader import DownloadManager


class Api:
    def __init__(self):
        self.scraper = Scraper()
        self.settings = config.load_settings()
        self.state = config.load_state()
        self._creators: dict[str, Creator] = {}
        self._posts: list[Post] = []
        self._manager: DownloadManager | None = None
        self._window = None

    def set_window(self, win):
        self._window = win

    def _emit(self, js_expr: str) -> None:
        # arayüze js gönder (worker thread'lerinden de çağrılır)
        if self._window is None:
            return
        try:
            self._window.evaluate_js(js_expr)
        except Exception:
            pass

    def _jstr(self, s) -> str:
        # güvenli json string (js'e gömmek için)
        return json.dumps(str(s), ensure_ascii=False)

    # -- ayarlar --------------------------------------------------------
    def get_settings(self) -> dict:
        return dict(self.settings)

    def save_settings(self, root: str, max_workers: int, delay: float,
                      filter_images: bool, filter_videos: bool) -> dict:
        self.settings["download_root"] = root or self.settings["download_root"]
        self.settings["max_workers"] = max(1, min(16, int(max_workers)))
        self.settings["delay"] = max(0.0, float(delay))
        self.settings["filter_images"] = bool(filter_images)
        self.settings["filter_videos"] = bool(filter_videos)
        config.save_settings(self.settings)
        return dict(self.settings)

    def pick_folder(self) -> str:
        if self._window is None:
            return ""
        try:
            result = self._window.create_file_dialog(
                webview.FOLDER_DIALOG, directory=self.settings.get("download_root", "")
            )
            if result:
                if isinstance(result, (list, tuple)):
                    return result[0] if result else ""
                return str(result)
        except Exception:
            pass
        return ""

    # -- favoriler & geçmiş --------------------------------------------
    def get_state(self) -> dict:
        return {
            "favorites": self.state.get("favorites", []),
            "history": self.state.get("history", []),
        }

    def toggle_favorite(self, key: str, name: str, service: str, id: str, avatar: str) -> dict:
        favs = self.state.setdefault("favorites", [])
        existing = next((f for f in favs if f.get("key") == key), None)
        if existing:
            favs = [f for f in favs if f.get("key") != key]
        else:
            favs.insert(0, {"key": key, "name": name, "service": service,
                            "id": id, "avatar": avatar})
            favs = favs[:config.max_favorites]
        self.state["favorites"] = favs
        config.save_state(self.state)
        return {"favorites": favs, "isFavorite": not existing}

    def remove_favorite(self, key: str) -> dict:
        self.state["favorites"] = [f for f in self.state.get("favorites", []) if f.get("key") != key]
        config.save_state(self.state)
        return {"favorites": self.state["favorites"]}

    def add_history(self, query: str) -> dict:
        q = (query or "").strip()
        if not q:
            return {"history": self.state.get("history", [])}
        hist = [h for h in self.state.get("history", []) if h != q]
        hist.insert(0, q)
        self.state["history"] = hist[:config.max_history]
        config.save_state(self.state)
        return {"history": self.state["history"]}

    def clear_history(self) -> dict:
        self.state["history"] = []
        config.save_state(self.state)
        return {"history": []}

    # -- arama ----------------------------------------------------------
    def search(self, query: str) -> list[dict]:
        try:
            self.scraper.reset_cancel()
            creators = self.scraper.search_creators(query or "")
        except ScraperCancelled:
            return []
        except Exception as e:
            self._emit(f"window.__searchError({json.dumps(str(e))})")
            return []
        if query and query.strip():
            self.add_history(query.strip())
            self._emit("window.__historyUpdated()")
        out = []
        for c in creators:
            key = f"{c.service}::{c.id}::{c.name}"
            self._creators[key] = c
            out.append({"key": key, "name": c.name, "service": c.service,
                        "id": c.id, "avatar": c.avatar})
        return out

    # -- post yükleme ---------------------------------------------------
    def load_all_posts(self, creator_key: str) -> dict:
        creator = self._creators.get(creator_key)
        if not creator:
            # favoriden açılışta creator kaydı olmayabilir, key'den kur
            try:
                service, cid, name = creator_key.split("::", 2)
            except Exception:
                return {"ok": False, "error": "Geçersiz creator"}
            creator = Creator(name=name, service=service, id=cid,
                              avatar=f"https://coomerfans.com/istorage/{cid}.jpg")
            self._creators[creator_key] = creator
        self.scraper.reset_cancel()
        self._posts = []

        def worker():
            try:
                for batch, has_next, page in self.scraper.iter_posts_batched(creator):
                    start = len(self._posts)
                    self._posts.extend(batch)
                    items = [{
                        "index": start + i,
                        "post_id": b.post_id,
                        "title": b.title,
                        "date": b.date,
                        "thumb": b.thumb,
                        "post_url": b.post_url,
                    } for i, b in enumerate(batch)]
                    payload = json.dumps({
                        "page": page,
                        "running": len(self._posts),
                        "has_next": has_next,
                        "items": items,
                    }, ensure_ascii=False)
                    self._emit(f"window.__postsBatch({payload})")
                self._emit(f"window.__postsDone({len(self._posts)})")
            except ScraperCancelled:
                self._emit(f"window.__postsDone({len(self._posts)})")
            except Exception as e:
                self._emit(f"window.__postsError({json.dumps(str(e), ensure_ascii=False)})")

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "creator": {"name": creator.name, "service": creator.service}}

    def cancel_load(self) -> None:
        self.scraper.cancel()

    def get_post_media(self, index: int) -> dict:
        # önizleme için tek postun medyasını yükle
        if not (0 <= index < len(self._posts)):
            return {"ok": False, "error": "Geçersiz post"}
        post = self._posts[index]
        if not post.loaded_media:
            try:
                self.scraper.load_post_media(post)
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {
            "ok": True,
            "title": post.title,
            "date": post.date,
            "post_url": post.post_url,
            "images": post.images,
            "videos": post.videos,
        }

    # -- indirme --------------------------------------------------------
    def start_download(self, post_indices: list[int] | None = None) -> dict:
        if not self._posts:
            return {"ok": False, "error": "Yüklü post yok"}
        if not post_indices:
            posts = list(self._posts)
        else:
            posts = [self._posts[i] for i in post_indices if 0 <= i < len(self._posts)]
        if not posts:
            return {"ok": False, "error": "Seçili post yok"}

        # creator adını bul (yoksa id kullan)
        ref = self._posts[0]
        creator_name = ref.creator_id
        for c in self._creators.values():
            if c.id == ref.creator_id and c.service == ref.service:
                creator_name = c.name
                break

        self.scraper.reset_cancel()
        self.scraper.delay = self.settings.get("delay", 0.4)
        filters = {
            "images": self.settings.get("filter_images", True),
            "videos": self.settings.get("filter_videos", True),
        }
        root = self.settings.get("download_root", config.default_settings["download_root"])
        try:
            os.makedirs(root, exist_ok=True)
        except OSError:
            pass

        mgr = DownloadManager(self.scraper, max_workers=self.settings.get("max_workers", 4))
        self._manager = mgr

        # indirme olaylarını arayüze köprüle
        mgr.on_log = lambda m: self._emit(f"window.__dlLog({self._jstr(m)})")
        mgr.on_progress = lambda d, t, _it: self._emit(f"window.__dlOverall({int(d)},{int(t)})")
        mgr.on_item_start = lambda it: self._emit(
            f"window.__dlStart({self._jstr(it.out_path)},{self._jstr(it.kind)},"
            f"{self._jstr(os.path.basename(it.out_path))})"
        )
        mgr.on_bytes = lambda it, r, t, sp: self._emit(
            f"window.__dlBytes({self._jstr(it.out_path)},{int(r)},{int(t)},{float(sp)})"
        )
        mgr.on_item_done = lambda it, ok: self._emit(
            f"window.__dlDone({self._jstr(it.out_path)},{'true' if ok else 'false'})"
        )
        mgr.on_finished = lambda: self._emit("window.__dlFinished()")

        # 1) medyaları paralel çek (tek tek değil, aynı anda N worker)
        self._emit('window.__dlStage("start",0,0,0)')
        t0 = time.time()
        prep_workers = max(4, int(self.settings.get("max_workers", 4)) * 2)

        def on_preload(i, n):
            elapsed = time.time() - t0
            eta = (elapsed / i) * (n - i) if i > 0 else 0.0
            self._emit(f"window.__dlStage({self._jstr('fetch')},{int(i)},{int(n)},0,{float(eta)})")

        mgr.preload_media(posts, on_progress=on_preload, max_workers=prep_workers)

        # 2) kuyruğa al (medya zaten yüklü, hızlı)
        def on_count(i, n, total):
            self._emit(f"window.__dlStage({self._jstr('queue')},{int(i)},{int(n)},{int(total)},0)")

        total = mgr.enqueue_posts(posts, root, creator_name, filters, on_count=on_count)
        if total == 0:
            self._emit('window.__dlLog("İndirilecek dosya bulunamadı.")')
            self._emit('window.__dlStage("empty",0,0,0)')
            return {"ok": False, "error": "İndirilecek dosya yok"}
        self._emit(f"window.__dlStage({self._jstr('ready')},0,0,{int(total)})")
        mgr.start(total)
        return {"ok": True, "total": total}

    def cancel_download(self) -> None:
        if self._manager:
            self._manager.cancel()
