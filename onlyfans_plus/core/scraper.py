"""CoomerFans sitesi scraping katmanı.

HTML tabanlı scraping yapar. coomerfans.com'un herkese açık bir JSON API'si olmadığı
için sayfa HTML'ini BeautifulSoup ile ayrıştırır.

URL sozlugu:
  - Arama:        GET /?q=<query>
  - Model sayfasi: GET /u/<service>/<id>/<name>  (sayfalama: ?page=N)
  - Gonderi:      GET /p/<post_id>/<id>/<service>
  - Avatar:       https://coomerfans.com/istorage/<id>.jpg
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://coomerfans.com"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# "Next" sayfalama baglantisi HTML icinde aranir (ham HTML uzerinde calisir).
_NEXT_PAGE_RE = re.compile(r'href="/u/[^"]+\?page=(\d+)"[^>]*>\s*Next', re.IGNORECASE)


def _split_path(path: str, prefix: str) -> list[str] | None:
    """'/u/onlyfans/316321/lurciferadollx' -> ['onlyfans','316321','lurciferadollx']
    prefix 'u' veya 'p' ile baslamayanlarda None doner."""
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 4 and parts[0] == prefix:
        return parts[1:4]
    return None


@dataclass
class Creator:
    name: str
    service: str
    id: str
    avatar: str = ""

    @property
    def url(self) -> str:
        return f"{BASE_URL}/u/{self.service}/{self.id}/{self.name}"


@dataclass
class Post:
    post_id: str
    creator_id: str
    service: str
    title: str
    date: str
    thumb: str = ""
    post_url: str = ""
    # lazy: sadece acildiginda doldurulur
    images: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)
    loaded_media: bool = False


class ScraperCancelled(Exception):
    """Arka plan yukleme iptal edildiginde firlatilir."""


class Scraper:
    """Site ile tum iletisimi yonetir."""

    def __init__(self, delay: float = 0.4, timeout: int = 20, proxy: str | None = None):
        import threading
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.delay = delay
        self.timeout = timeout
        self._last_request = 0.0
        self._cancel = threading.Event()
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

    def cancel(self) -> None:
        """Devam eden arka plan isteklerin bir an once sonlanmasini saglar."""
        self._cancel.set()

    def reset_cancel(self) -> None:
        self._cancel.clear()

    def clone(self) -> "Scraper":
        """Ayni ayarlarda ama kendi session/thread guvenli kopyasi.
        Paralel medya cekme icin kullanilir; cancel event'i paylasilir."""
        s = Scraper(delay=self.delay, timeout=self.timeout)
        s._cancel = self._cancel  # iptali paylas
        s.session.headers.update(dict(self.session.headers))
        try:
            s.session.proxies.update(dict(self.session.proxies))
        except Exception:  # noqa: BLE001
            pass
        return s

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise ScraperCancelled()

    # ------------------------------------------------------------------ #
    # Dusuk seviyeli istek
    # ------------------------------------------------------------------ #
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            # kucuk adimlarla bekle ki cancel aninda响应 versin
            remaining = self.delay - elapsed
            step = 0.05
            while remaining > 0 and not self._cancel.is_set():
                time.sleep(min(step, remaining))
                remaining -= step
        self._check_cancel()
        self._last_request = time.time()

    def get(self, url: str) -> str:
        """Throttle uygulanmis GET. HTML metni doner."""
        self._throttle()
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def stream(self, url: str, chunk_size: int = 65536, timeout: int | None = None,
               headers: dict | None = None):
        """Indirme icin streaming GET. (resp, content_length) doner.

        timeout: None ise self.timeout kullanilir. headers: ekstra header'lar
        (ornegin Range ile resume).
        """
        self._throttle()
        h = None
        if headers:
            h = dict(headers)
        resp = self.session.get(url, stream=True, timeout=timeout or self.timeout,
                                headers=h)
        resp.raise_for_status()
        size = int(resp.headers.get("Content-Length", 0))
        return resp, size

    # ------------------------------------------------------------------ #
    # Arama
    # ------------------------------------------------------------------ #
    def search_creators(self, query: str) -> list[Creator]:
        if not query.strip():
            return []
        html = self.get(f"{BASE_URL}/?q={requests.utils.quote(query)}")
        soup = BeautifulSoup(html, "html.parser")
        creators: list[Creator] = []
        seen: set[str] = set()
        for a in soup.select("a[href^='/u/']"):
            href = a.get("href", "")
            parsed = _split_path(href, "u")
            if not parsed:
                continue
            service, cid, name = parsed
            key = f"{service}:{cid}"
            if key in seen:
                continue
            seen.add(key)
            creators.append(
                Creator(
                    name=name,
                    service=service,
                    id=cid,
                    avatar=f"{BASE_URL}/istorage/{cid}.jpg",
                )
            )
        return creators

    # ------------------------------------------------------------------ #
    # Gonderi listesi
    # ------------------------------------------------------------------ #
    def _parse_posts_page(self, html: str, service: str, creator_id: str) -> list[Post]:
        soup = BeautifulSoup(html, "html.parser")
        posts: list[Post] = []
        for post_div in soup.select("div.posts-list > div.post"):
            h3 = post_div.select_one("h3 a")
            post_id = ""
            if h3:
                parsed = _split_path(h3.get("href", ""), "p")
                if parsed:
                    post_id = parsed[0]
            title = (h3.get_text(strip=True) if h3 else "") or "(başlıksız)"
            date_el = post_div.select_one("span.post-date")
            date = date_el.get_text(strip=True) if date_el else ""
            thumb = ""
            thumb_img = post_div.select_one("div.post-thumbs img")
            if thumb_img:
                thumb = thumb_img.get("src", "")
            if not post_id:
                continue
            posts.append(
                Post(
                    post_id=post_id,
                    creator_id=creator_id,
                    service=service,
                    title=title,
                    date=date,
                    thumb=thumb,
                    post_url=f"{BASE_URL}/p/{post_id}/{creator_id}/{service}",
                )
            )
        return posts

    def get_posts_page(self, creator: Creator, page: int) -> tuple[list[Post], bool]:
        """Tek sayfa gonderisi + 'Next' var mi doner."""
        url = creator.url if page <= 1 else f"{creator.url}?page={page}"
        html = self.get(url)
        posts = self._parse_posts_page(html, creator.service, creator.id)
        has_next = bool(_NEXT_PAGE_RE.search(html))
        return posts, has_next

    def count_posts(self, creator: Creator, progress_cb=None, max_pages: int = 200) -> int:
        """Tum sayfalari gezerek gonderi sayisini sayar."""
        total = 0
        page = 1
        while page <= max_pages:
            posts, has_next = self.get_posts_page(creator, page)
            total += len(posts)
            if progress_cb:
                progress_cb(page, total)
            if not has_next or not posts:
                break
            page += 1
        return total

    def iter_posts(self, creator: Creator, max_pages: int = 200) -> Iterable[Post]:
        """Tum gonderileri sayfa sayfa yield eder."""
        for batch, _has_next, _page in self.iter_posts_batched(creator, max_pages):
            for p in batch:
                yield p

    def iter_posts_batched(self, creator: Creator, max_pages: int = 200):
        """Her sayfa icin (posts, has_next, page) yield eder.

        GUI bunu kullanarak tum postlari progresif (sayfa sayfa) yukler;
        'daha fazla yukle' butonuna ihtiyac birakmaz.
        """
        page = 1
        while page <= max_pages:
            posts, has_next = self.get_posts_page(creator, page)
            yield posts, has_next, page
            if not has_next or not posts:
                break
            page += 1

    # ------------------------------------------------------------------ #
    # Gonderi medya ayristirma
    # ------------------------------------------------------------------ #
    def load_post_media(self, post: Post) -> Post:
        """Gonderi sayfasini cekip image/video URL'lerini doldurur."""
        html = self.get(post.post_url)
        soup = BeautifulSoup(html, "html.parser")
        body = soup.select_one("div.post-body")
        if not body:
            post.loaded_media = True
            return post
        # post-body icindeki direkt img ve source etiketleri
        for img in body.find_all("img"):
            src = img.get("src", "")
            if src and "/istorage/" not in src:  # avatarlari ele
                post.images.append(self._abs(src))
        for source in body.find_all("source"):
            src = source.get("src", "")
            if src:
                post.videos.append(self._abs(src))
        post.loaded_media = True
        return post

    @staticmethod
    def _abs(url: str) -> str:
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return urljoin(BASE_URL, url)
        return url

    # ------------------------------------------------------------------ #
    # Taze video URL'si
    # ------------------------------------------------------------------ #
    def refresh_video_urls(self, post: Post) -> list[str]:
        """Video URL'leri zaman sinirli oldugu icin indirme aninda taze halini doner."""
        fresh = self.load_post_media(Post(
            post_id=post.post_id, creator_id=post.creator_id, service=post.service,
            title=post.title, date=post.date, post_url=post.post_url,
        ))
        return fresh.videos


def file_name_from_url(url: str) -> str:
    """URL'den dosya adi cikarir (query string olmadan)."""
    path = urlparse(url).path
    return path.rsplit("/", 1)[-1] or "file"
