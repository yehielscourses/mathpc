#!/usr/bin/env python3
"""Télécharge les annales bac spé maths et spé physique-chimie (2021-2025)."""

from __future__ import annotations

import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
YEARS = list(range(2021, 2026))
BASE_SUJETDEBAC = "https://www.sujetdebac.fr"
BASE_APMEP = "https://www.apmep.fr"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

USER_AGENT = "Mozilla/5.0 (compatible; AnnalesDownloader/1.0)"


def fetch(url: str, retries: int = 3) -> bytes:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, context=CTX, timeout=60) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"Échec téléchargement {url}: {last_err}")


def fetch_text(url: str) -> str:
    return fetch(url).decode("utf-8", errors="replace")


def save_pdf(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1000:
        return False
    data = fetch(url)
    if len(data) < 500:
        return False
    dest.write_bytes(data)
    return True


def download_sujetdebac(subject_slug: str, out_dir: Path) -> dict[str, int]:
    stats = {"sujets": 0, "corriges": 0, "skipped": 0}
    for year in YEARS:
        index_url = f"{BASE_SUJETDEBAC}/annales/specialites/{subject_slug}/{year}/"
        html = fetch_text(index_url)
        pages = sorted(
            set(re.findall(rf'href="(/annales/{re.escape(subject_slug)}-[^"]+)"', html))
        )
        for page in pages:
            page_html = fetch_text(BASE_SUJETDEBAC + page)
            pdfs = re.findall(r'href="(/annales-pdf/[^"]+\.pdf)"', page_html)
            slug = page.rsplit("/", 1)[-1]
            for pdf_path in pdfs:
                filename = pdf_path.rsplit("/", 1)[-1]
                if "corrige" in filename or "correction" in filename:
                    kind = "corriges"
                    stats["corriges"] += 1
                elif "sujet" in filename:
                    kind = "sujets"
                    stats["sujets"] += 1
                else:
                    kind = "autres"
                dest = out_dir / str(year) / kind / filename
                if save_pdf(BASE_SUJETDEBAC + pdf_path, dest):
                    print(f"  [pc] {dest.relative_to(ROOT)}")
                else:
                    stats["skipped"] += 1
            time.sleep(0.15)
    return stats


def is_apmep_corrige(name: str) -> bool:
    lower = name.lower()
    return "corrige" in lower or "corrigé" in lower or lower.startswith("corr_")


def download_apmep_math(out_dir: Path) -> dict[str, int]:
    stats = {"sujets": 0, "corriges": 0, "skipped": 0}
    for year in YEARS:
        html = fetch_text(f"{BASE_APMEP}/Annee-{year}")
        pdfs = sorted(set(re.findall(r'href="(IMG/pdf/[^"]+\.pdf)"', html)))
        for rel in pdfs:
            filename = rel.rsplit("/", 1)[-1]
            kind = "corriges" if is_apmep_corrige(filename) else "sujets"
            dest = out_dir / str(year) / kind / filename
            url = urljoin(BASE_APMEP + "/", rel)
            if save_pdf(url, dest):
                print(f"  [math] {dest.relative_to(ROOT)}")
                stats[kind] += 1
            else:
                stats["skipped"] += 1
            time.sleep(0.1)
    return stats


def main() -> None:
    math_dir = ROOT / "math"
    pc_dir = ROOT / "physique-chimie"

    print("=== Téléchargement spé Mathématiques (APMEP) ===")
    math_stats = download_apmep_math(math_dir)
    print(math_stats)

    print("=== Téléchargement spé Physique-Chimie (sujetdebac.fr) ===")
    pc_stats = download_sujetdebac("spe-physique-chimie", pc_dir)
    print(pc_stats)


if __name__ == "__main__":
    main()
