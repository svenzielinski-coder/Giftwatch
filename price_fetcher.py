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
    except:
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

def fetch_price(url: str, timeout: int = 20) -> Tuple[Optional[float], Optional[str], str]:
    headers = {"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"}
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")

    # 1) JSON-LD Offer / AggregateOffer
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.get_text(strip=True))
        except:
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
            try:
                if obj.get("@type") in ("Offer", "AggregateOffer"):
                    if "price" in obj:
                        p = _to_float(str(obj.get("price")))
                        cur = obj.get("priceCurrency") or _pick_currency(str(obj))
                        if p is not None:
                            return p, (cur or "EUR"), "json-ld"
                    if "lowPrice" in obj:
                        p = _to_float(str(obj.get("lowPrice")))
                        cur = obj.get("priceCurrency") or _pick_currency(str(obj))
                        if p is not None:
                            return p, (cur or "EUR"), "json-ld-lowPrice"
            except:
                pass

    # 2) Meta tags
    for attr in [
        ("property", "product:price:amount"),
        ("property", "og:price:amount"),
        ("property", "product:price"),
        ("name", "twitter:data1"),
    ]:
        m = soup.find("meta", attrs={attr[0]: attr[1]})
        if m and m.get("content"):
            p = _to_float(m["content"])
            if p is not None:
                cur = _pick_currency(m["content"]) or "EUR"
                return p, cur, f"meta:{attr[1]}"

    # 3) Heuristik: Preis mit Eurozeichen im Text
    text = soup.get_text(" ", strip=True)
    m = re.search(r"(\d{1,3}([.,]\d{3})*([.,]\d{2})?)\s?€", text)
    if m:
        p = _to_float(m.group(0))
        if p is not None:
            return p, "EUR", "heuristic-eur"

    return None, None, "not-found"
