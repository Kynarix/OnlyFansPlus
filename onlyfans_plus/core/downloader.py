"""Cok kanalli indirme yoneticisi.

PyQt sinyalleri ile GUI'ye ilerlemeyi bildirir. Her gonderi bir klasore indirilir:
  <root>/<service>/<creator_name>/<post_id>_<sanitized_title>/

Video URL'leri zaman sinirli oldugu icin, her video icin indirme oncesi scraper
uzerinden taze URL alinir.

Hata toleransi:
  - Windows icin guvenli klasor/dosya adi sanitizasyonu (trailing dot, '..', yasak
    karakterler, reserved isimler).
  - Baglanti/timeout hatalarinda yeniden deneme (resume destegi ile).
"""

from __future__ import annotations

import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from queue import Queue, Empty

from .scraper import Scraper, Post, file_name_from_url


# Windows'ta yasak karakterler + reserved isimler
_WIN_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_NAME = 120  # tek bir path bileseni icin guvenli ust sinir


def _safe_name(name: str, fallback: str) -> str:
    """Windows (ve POSIX) icin guvenli tek path bileseni uretir."""
    # yasak karakterleri yok et
    s = _WIN_FORBIDDEN.sub("", name)
    # nokta ve bosluk kümelerini sikistir; '..' dizilerini kaldir (Windows rezerve)
    s = s.replace("..", "")
    # uzun soyut alanlari kaldir
    s = re.sub(r"\s+", " ", s).strip()
    # trailing dot/bosluk (Windows icin) — Windows bunlari sessizce keser ve
    # farkli bir klasor olusturup sonra .part yazamamiza sebep olur
    s = s.rstrip(". ")
    # uzunluk siniri
    s = s[:MAX_NAME].rstrip(". ")
    if not s or s.upper() in _WIN_RESERVED or s in {".", ".."}:
        s = fallback
    return s


@dataclass
class DownloadItem:
    post: Post
    kind: str  # "image" | "video"
    url: str
    out_path: str


class DownloadManager:
    """Thread-safe indirme kuyrugu."""

    def __init__(self, scraper: Scraper, max_workers: int = 3,
                 max_retries: int = 3, download_timeout: int = 60):
        self.scraper = scraper
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.download_timeout = download_timeout
        self._executor: ThreadPoolExecutor | None = None
        self._futures: list[Future] = []
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._queue: Queue[DownloadItem | None] = Queue()
        self._total = 0
        self._done = 0
        self._failed = 0
        # GUI callback'leri
        self.on_progress = None  # (done, total, current_item)
        self.on_item_start = None  # (item)
        self.on_item_done = None  # (item, ok)
        self.on_log = None  # (message)
        self.on_finished = None  # ()
        self.on_bytes = None  # (item, received, total, speed_bps) — canlı dosya ilerlemesi

    # ------------------------------------------------------------------ #
    def enqueue_post(self, post: Post, root: str, creator_name: str, filters: dict) -> int:
        """Bir gonderiyi indirilecek medyalar haline getirip kuyruğa ekler.

        filters: {"images": bool, "videos": bool}
        Donus: eklenen dosya sayisi.
        """
        if not post.loaded_media:
            try:
                self.scraper.load_post_media(post)
            except Exception as e:  # noqa: BLE001
                if self.on_log:
                    self.on_log(f"[!] Medya alınamadı ({post.post_id}): {e}")
                return 0

        folder = self._post_folder(root, post.service, creator_name, post)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            # son care: sadece post_id ile klasor dene
            folder = os.path.join(root, post.service, _safe_name(creator_name, "creator"),
                                  str(post.post_id))
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as e2:
                if self.on_log:
                    self.on_log(f"[!] Klasör oluşturulamadı ({post.post_id}): {e2}")
                return 0

        added = 0
        if filters.get("images", True):
            for url in post.images:
                name = _safe_name(file_name_from_url(url), "image")
                item = DownloadItem(post, "image", url, os.path.join(folder, name))
                self._queue.put(item)
                added += 1
        if filters.get("videos", True):
            for url in post.videos:
                name = _safe_name(file_name_from_url(url.split("?")[0]), "video")
                item = DownloadItem(post, "video", url, os.path.join(folder, name))
                self._queue.put(item)
                added += 1
        return added

    def enqueue_posts(self, posts: list[Post], root: str, creator_name: str,
                      filters: dict, on_count=None) -> int:
        total = 0
        for i, p in enumerate(posts, 1):
            total += self.enqueue_post(p, root, creator_name, filters)
            if on_count:
                on_count(i, len(posts), total)
        return total

    # ------------------------------------------------------------------ #
    def preload_media(self, posts: list[Post], on_progress=None,
                      max_workers: int = 8) -> None:
        """Postlarin medya URL'lerini paralel olarak ceker.

        Her worker kendi Scraper klonunu kullanir (ayni delay/timeout, paylasilan
        cancel). Bu, tek tek sira ile cekmeye gore cok daha hizlidir:
        248 post ~100sn yerine ~12-15sn. Cekilen medya enqueue_post tarafindan
        tekrar cekilmez (loaded_media=True).
        """
        from queue import Queue, Empty
        from concurrent.futures import ThreadPoolExecutor, as_completed

        workers = max(1, min(int(max_workers), 16))
        n = len(posts)
        if n == 0:
            return
        scrapers_q: Queue = Queue()
        for _ in range(workers):
            scrapers_q.put(self.scraper.clone())

        def task(idx: int) -> int:
            p = posts[idx]
            try:
                sc = scrapers_q.get(timeout=10)
            except Empty:
                sc = self.scraper
            try:
                if not p.loaded_media and not self._cancelled.is_set():
                    try:
                        sc.load_post_media(p)
                    except Exception:  # noqa: BLE001
                        pass
            finally:
                scrapers_q.put(sc)
            return idx

        done = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(task, i) for i in range(n)]
            for f in as_completed(futs):
                done += 1
                if on_progress:
                    on_progress(done, n)
        ex.shutdown(wait=False)

    # ------------------------------------------------------------------ #
    def start(self, total: int) -> None:
        self._total = total
        self._done = 0
        self._failed = 0
        self._cancelled.clear()
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        for _ in range(self.max_workers):
            self._futures.append(self._executor.submit(self._worker))
        threading.Thread(target=self._await_completion, daemon=True).start()

    def _await_completion(self) -> None:
        for f in self._futures:
            try:
                f.result()
            except Exception as e:  # noqa: BLE001
                if self.on_log:
                    self.on_log(f"[!] Worker hatası: {e}")
        if self._executor:
            self._executor.shutdown(wait=False)
        if self.on_finished:
            self.on_finished()

    def cancel(self) -> None:
        self._cancelled.set()
        try:
            while True:
                self._queue.get_nowait()
        except Empty:
            pass
        self._queue.put(None)

    def _worker(self) -> None:
        while not self._cancelled.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except Empty:
                continue
            if item is None:
                self._queue.task_done()
                return
            try:
                self._download(item)
            finally:
                with self._lock:
                    self._done += 1
                if self.on_progress:
                    self.on_progress(self._done, self._total, item)
                self._queue.task_done()

    # ------------------------------------------------------------------ #
    def _download(self, item: DownloadItem) -> None:
        if os.path.exists(item.out_path) and os.path.getsize(item.out_path) > 0:
            if self.on_log:
                self.on_log(f"[=] Zaten var, atlanıyor: {os.path.basename(item.out_path)}")
            if self.on_item_done:
                self.on_item_done(item, True)
            return

        if self.on_item_start:
            self.on_item_start(item)

        base = file_name_from_url(item.url.split("?")[0])
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            if self._cancelled.is_set():
                return
            url = item.url
            if item.kind == "video":
                # her denemede taze URL al (onceki deneme sirasinda sure dolabilir)
                try:
                    fresh = self.scraper.refresh_video_urls(item.post)
                    matched = next((fu for fu in fresh if base in fu), None)
                    url = matched or (fresh[0] if fresh else url)
                except Exception as e:  # noqa: BLE001
                    if attempt == 1 and self.on_log:
                        self.on_log(f"[!] Taze video URL alınamadı: {e}")
            try:
                ok = self._fetch_to_file(url, item)
            except Exception as e:  # noqa: BLE001
                last_err = e
                ok = False
            if ok:
                return
            if self._cancelled.is_set():
                return
            last_err = last_err or "indirme başarısız"
            if attempt < self.max_retries:
                backoff = 1.5 * attempt
                if self.on_log:
                    self.on_log(f"[↻] Yeniden denenecek ({attempt}/{self.max_retries}) "
                                f"{os.path.basename(item.out_path)} — {last_err}")
                time.sleep(backoff)

        with self._lock:
            self._failed += 1
        if self.on_log:
            self.on_log(f"[✗] {item.kind.upper()} → {os.path.basename(item.out_path)}: {last_err}")
        if self.on_item_done:
            self.on_item_done(item, False)

    def _fetch_to_file(self, url: str, item: DownloadItem) -> bool:
        """Tek bir URL'i .part dosyasina indirir (resume destekli), sonra replace.

        True dondururse basarili. Hata firlatirsa ust katman yakalar.
        Indirme sirasinda on_bytes ile canli byte/hiz bilgisini emit eder.
        """
        tmp = item.out_path + ".part"
        existing = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        headers = {"Range": f"bytes={existing}-"} if existing else None
        resp, resp_size = self.scraper.stream(url, timeout=self.download_timeout,
                                              headers=headers)
        mode = "ab" if (existing and resp.status_code == 206) else "wb"
        # toplam boyut: resume durumunda existing + kalan; bilinmiyorsa 0
        total = (existing + resp_size) if (existing and resp.status_code == 206) else resp_size
        received = existing
        t0 = time.time()
        last_emit = 0.0
        try:
            if self.on_bytes:
                self.on_bytes(item, received, total, 0.0)
            with open(tmp, mode) as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    if self._cancelled.is_set():
                        fh.close()
                        return False
                    if chunk:
                        fh.write(chunk)
                        received += len(chunk)
                        now = time.time()
                        if self.on_bytes and (now - last_emit) >= 0.08:
                            elapsed = max(now - t0, 1e-6)
                            # bu denemedeki indirilen miktar = received - existing
                            speed = (received - existing) / elapsed
                            self.on_bytes(item, received, total, speed)
                            last_emit = now
            # bos dosya korumasi
            if os.path.getsize(tmp) == 0:
                try: os.remove(tmp)
                except OSError: pass
                raise IOError("boş yanıt")
            os.replace(tmp, item.out_path)
            if self.on_bytes:
                self.on_bytes(item, received, max(total, received), 0.0)
            if self.on_log:
                self.on_log(f"[✓] {item.kind.upper()} → {os.path.basename(item.out_path)}")
            if self.on_item_done:
                self.on_item_done(item, True)
            return True
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ #
    @staticmethod
    def _post_folder(root: str, service: str, creator_name: str, post: Post) -> str:
        safe_service = _safe_name(service, "service")
        safe_creator = _safe_name(creator_name, "creator")
        safe_title = _safe_name(post.title, "post") or "untitled"
        # title kisaltmasi klasor adi gerekcek; post_id ile birlestir
        folder_name = _safe_name(f"{post.post_id}_{safe_title}", str(post.post_id))
        return os.path.join(root, safe_service, safe_creator, folder_name)
