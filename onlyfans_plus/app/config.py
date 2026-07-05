"""yollar, ayarlar ve durum (favoriler/geçmiş) burada."""

from __future__ import annotations

import json
import os
import sys

# exe modunda ayarlar yazılabilir bir kullanıcı dizininde durur
# (onefile _MEIPASS geçici ve salt okunur). geliştirme modunda paket içinde.
if getattr(sys, "frozen", False):
    _root = os.environ.get("APPDATA") or os.path.expanduser("~")
    data_dir = os.path.join(_root, "OnlyFans+", "data")
else:
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(pkg_dir, "data")
os.makedirs(data_dir, exist_ok=True)

settings_path = os.path.join(data_dir, "settings.json")
state_path = os.path.join(data_dir, "state.json")

default_settings = {
    "download_root": os.path.join(os.path.expanduser("~"), "Downloads", "OnlyFans+"),
    "max_workers": 4,
    "delay": 0.4,
    "filter_images": True,
    "filter_videos": True,
}

max_history = 15
max_favorites = 200


def load_settings() -> dict:
    # kayıtlı ayarları oku, eksik alanları varsayılanla tamamlar
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            s = json.load(f)
        merged = dict(default_settings)
        merged.update(s)
        return merged
    except Exception:
        return dict(default_settings)


def save_settings(s: dict) -> None:
    try:
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_state() -> dict:
    # favoriler ve geçmiş aramalar
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            st = json.load(f)
        return {
            "favorites": st.get("favorites", [])[:max_favorites],
            "history": st.get("history", [])[:max_history],
        }
    except Exception:
        return {"favorites": [], "history": []}


def save_state(st: dict) -> None:
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
