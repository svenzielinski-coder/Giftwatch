import re
import json
import requests
from bs4 import BeautifulSoup
from typing import Optional, Tuple

UA = "Mozilla/5.0 (compatible; GiftWatch/1.0)"

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

def fetch_price(url: str, timeout: int = 15) -> Tuple[Optional[float], Optional[str], str]:
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

    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
    except requests.RequestException as e:
        return None, None, f"request-error:{type(e).__name__}"

    # Parser: lxml ist ok, aber falls auf Cloud mal Ärger ist, fallback auf html.parser
    try:
        soup = BeautifulSoup(r.text, "lxml")
    except Exception:
        soup = BeautifulSoup(r.text, "html.parser")

    # 1) JSON-LD Offer / AggregateOffer
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        def walk(obj):
            if isinstance(obj, dict):
                yield obj
                for v in obj.values():
                    yield from walk(v)
            elif isinstance(obj, list):
                for it in obj:
                    yield from walk(it)

        for obj in walk(data):
            if not isinstance(obj, dict):
                continue
            try:
                if obj.get("@type") in ("Offer", "AggregateOffer"):
                    if "price" in obj:
                        p = _to_float(str(obj.get("price")))
                        cur = obj.get("priceCurrency") or _pick_currency(str(obj))
                        if p is not None:
                            return p, (cur or "EUR"), "json-ld:price"
                    if "lowPrice" in obj:
                        p = _to_float(str(obj.get("lowPrice")))
                        cur = obj.get("priceCurrency") or _pick_currency(str(obj))
                        if p is not None:
                            return p, (cur or "EUR"), "json-ld:lowPrice"
            except Exception:
                pass

    # 2) Meta-Tags (häufig bei Shops)
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

    # 3) Heuristik: Preis im sichtbaren Text
    # EUR
    text = soup.get_text(" ", strip=True)
    m = re.search(r"(\d{1,3}([.,]\d{3})*([.,]\d{2})?)\s?€", text)
    if m:
        p = _to_float(m.group(0))
        if p is not None:
            return p, "EUR", "text:eur"

    # USD
    m = re.search(r"\$\s?(\d{1,3}([.,]\d{3})*([.,]\d{2})?)", text)
    if m:
        p = _to_float(m.group(0))
        if p is not None:
            return p, "USD", "text:usd"

    # CHF
    m = re.search(r"(\d{1,3}([.,]\d{3})*([.,]\d{2})?)\s?CHF", text, flags=re.IGNORECASE)
    if m:
        p = _to_float(m.group(0))
        if p is not None:
            return p, "CHF", "text:chf"

    # GBP
    m = re.search(r"£\s?(\d{1,3}([.,]\d{3})*([.,]\d{2})?)", text)
    if m:
        p = _to_float(m.group(0))
        if p is not None:
            return p, "GBP", "text:gbp"

    return None, None, "not-found"
