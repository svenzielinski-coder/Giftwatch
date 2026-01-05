from __future__ import annotations

import re
import json
import time
import random
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup

# ----------------------------
# Config
# ----------------------------
UA = "Mozilla/5.0 (compatible; GiftWatch/1.0; +https://github.com/svenzielinski-coder/Giftwatch)"
TIMEOUT = 15
MAX_RETRIES = 2
MAX_TEXT_LEN = 200_000  # Schutz gegen riesige Seiten


# ----------------------------
# Helpers
# ----------------------------
def _to_float(price_str: str) -> Optional[float]:
    if not price_str:
        return None

    s = price_str.strip()
    s = re.sub(r"[^\d,\.]", "", s)

    if s.count(",") == 1 and s.count(".") >= 1:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    else:
        if s.count(".") > 1:
            parts = s.split(".")
            s = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return float(s)
    except Exception:
        return None


def _pick_currency(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.upper()
    if "€" in t or "EUR" in t:
        return "EUR"
    if "$" in t or "USD" in t:
        return "USD"
    if "CHF" in t:
        return "CHF"
    if "£" in t or "GBP" in t:
        return "GBP"
    return None


def _iter_json(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_json(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _iter_json(it)


# ----------------------------
# Main API
# ----------------------------
def fetch_price(url: str, timeout: int = TIMEOUT) -> Tuple[Optional[float], Optional[str], str]:
    """
    Returns: (price, currency, source)
    price: float | None
    currency: str | None
    source: str (debug/info)
    """

    headers = {
        "User-Agent": UA,
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    session = requests.Session()
    last_error: Optional[str] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
            r.raise_for_status()
            html = r.text
            break
        except requests.RequestException as e:
            last_error = f"{type(e).__name__}"
            if attempt >= MAX_RETRIES:
                return None, None, f"request-error:{last_error}"
            # kurzer Backoff + Jitter
            time.sleep(0.6 + random.random() * 0.4)
    else:
        return None, None, "request-error"

    # Parser
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    # ----------------------------
    # 1) JSON-LD (Offer / AggregateOffer)
    # ----------------------------
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        for obj in _iter_json(data):
            if not isinstance(obj, dict):
                continue
            if obj.get("@type") not in ("Offer", "AggregateOffer"):
                continue

            # bevorzugt "price" vor "lowPrice"
            for key in ("price", "lowPrice"):
                if key in obj:
                    p = _to_float(str(obj.get(key)))
                    if p is None:
                        continue
                    cur = obj.get("priceCurrency") or _pick_currency(str(obj)) or "EUR"
                    return p, cur, f"json-ld:{key}"

    # ----------------------------
    # 2) Meta-Tags
    # ----------------------------
    meta_candidates = [
        ("property", "product:price:amount"),
        ("property", "og:price:amount"),
        ("property", "product:price"),
        ("name", "twitter:data1"),
        ("name", "price"),
    ]

    for key, val in meta_candidates:
        m = soup.find("meta", attrs={key: val})
        if m and m.get("content"):
            content = m["content"]
            p = _to_float(content)
            if p is not None:
                cur = _pick_currency(content) or "EUR"
                return p, cur, f"meta:{val}"

    # ----------------------------
    # 3) Text-Heuristik (limitiert)
    # ----------------------------
    text = soup.get_text(" ", strip=True)
    if len(text) > MAX_TEXT_LEN:
        text = text[:MAX_TEXT_LEN]

    patterns = [
        (r"(\d{1,3}([.,]\d{3})*([.,]\d{2})?)\s?€", "EUR"),
        (r"\$\s?(\d{1,3}([.,]\d{3})*([.,]\d{2})?)", "USD"),
        (r"(\d{1,3}([.,]\d{3})*([.,]\d{2})?)\s?CHF", "CHF"),
        (r"£\s?(\d{1,3}([.,]\d{3})*([.,]\d{2})?)", "GBP"),
    ]

    for pat, cur in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            p = _to_float(m.group(0))
            if p is not None:
                return p, cur, f"text:{cur.lower()}"

    return None, None, "not-found"
