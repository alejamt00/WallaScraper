from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import os, re, random, unicodedata

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout, Route, Request, ElementHandle

@dataclass
class WItem:
    id: str
    title: str
    price: float             # ahora float con decimales
    url: str
    seller_id: str = ""      # compat
    reserved: bool = False
    sold: bool = False
    shipping: bool = False   # envío disponible (por badge)

# ===========================
# Config
# ===========================
WALLA_HTML_BASE = "https://es.wallapop.com"
PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "1") != "0"
WALLA_TIMEOUT_MS = int(float(os.getenv("WALLA_TIMEOUT", "12.0")) * 1000)
MAX_ITEMS = int(os.getenv("WALLA_MAX_ITEMS", "40"))

DEFAULT_LAT = float(os.getenv("WALLA_LAT", "40.4168"))
DEFAULT_LON = float(os.getenv("WALLA_LON", "-3.7038"))
DEFAULT_KM  = int(os.getenv("WALLA_DEFAULT_KM", "200"))

WALLA_BLOCK_RESOURCES = os.getenv("WALLA_BLOCK_RESOURCES", "1") != "0"

UA_DEFAULT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEBUG = os.getenv("WALLA_DEBUG", "0") == "1"

# ===========================
# Utils
# ===========================
def _log(msg: str):
    if DEBUG:
        print(msg)

def _to_price(text: str) -> float:
    """Convierte texto '12,50 €' en float 12.5"""
    if not text:
        return 0.0
    try:
        text = text.replace("\xa0", " ").strip()
        if re.search(r"\d\s+\d", text):  # descarta "3 80"
            return 0.0
        num = re.sub(r"[^\d,\.]", "", text)
        num = num.replace(".", "").replace(",", ".")
        return float(num) if num else 0.0
    except Exception:
        return 0.0

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[\W_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _tokenize_query(q: str) -> List[str]:
    return [t for t in _norm(q).split(" ") if len(t) >= 2]

def _title_matches_query(title: str, q: str, strict: bool = True) -> bool:
    t = _norm(title)
    tokens = _tokenize_query(q)
    if not tokens:
        return True
    return all(tok in t for tok in tokens) if strict else any(tok in t for tok in tokens)

def _score_title(title: str, q: str) -> int:
    t = _norm(title)
    qn = _norm(q)
    toks = _tokenize_query(q)
    score = 0
    if toks and all(tok in t for tok in toks): score += 3
    if qn in t: score += 2
    if toks and t.startswith(toks[0]): score += 1
    return score

def _contains_omit(title: str, omit_words: List[str]) -> bool:
    """Devuelve True si el título contiene alguna palabra prohibida"""
    t = _norm(title)
    for w in omit_words:
        if _norm(w) in t:
            return True
    return False

# ===========================
# URL correcta
# ===========================
def _build_search_url(query: str, filters: Optional[Dict[str, Any]] = None) -> str:
    from urllib.parse import urlencode
    filters = filters or {}
    params = {
        "keywords": query,
        "source": "side_bar_filters",
    }
    if "min" in filters:
        params["min_sale_price"] = float(filters["min"])
    if "max" in filters:
        params["max_sale_price"] = float(filters["max"])
    if filters.get("shipping"):
        params["is_shippable"] = "true"
    if "km" in filters:
        params["latitude"] = DEFAULT_LAT
        params["longitude"] = DEFAULT_LON
        params["distance"] = int(filters["km"])
    return f"{WALLA_HTML_BASE}/search?{urlencode(params)}"

# ===========================
# Helpers Playwright
# ===========================
async def _dismiss_cookies(page: Page) -> None:
    try:
        for sel in [
            '#onetrust-reject-all-handler',
            '#onetrust-accept-btn-handler',
            '.ot-pc-refuse-all-handler',
            '.ot-pc-accept-all-handler',
        ]:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                await page.wait_for_timeout(120)
                return
    except Exception:
        pass

async def _block_heavy_resources(route: Route, request: Request):
    if request.resource_type in {"image", "media", "font"}:
        await route.abort()
    else:
        await route.continue_()

# ---- Precio ----
BAD_CTX = ["envio", "envío", "desde", "al mes", "mes", "finan", "cuota", "cuotas", "pagar"]

async def _price_from_text(txt: str) -> float:
    out = 0.0
    for m in re.finditer(r"(\d+(?:[.,]\d{1,2})?)\s*€", txt.replace("\xa0", " ")):
        raw = m.group(1)
        if " " in raw:
            continue
        val = _to_price(raw + "€")
        if val >= 0.01:
            start = max(0, m.start() - 30)
            end   = min(len(txt), m.end() + 30)
            ctx = txt[start:end].lower()
            if any(b in ctx for b in BAD_CTX):
                continue
            out = max(out, val)
    return out

async def _price_from_anchor(a_el: ElementHandle) -> float:
    node = await a_el.query_selector("strong[aria-label*='price' i]")
    if node:
        try:
            txt = (await node.inner_text() or "").strip()
            v = _to_price(txt)
            if DEBUG: _log(f"[PRICE strong='{txt}'] -> {v}")
            if v >= 0.01:
                return v
        except Exception:
            pass
    for sel in (
        '[data-qa="ad-card-price"]',
        '[data-qa*="price"]',
        '[data-testid*="price"]',
        '[aria-label*="price" i]',
        'span[class*="price"]',
        'div[class*="price"]',
        'p[class*="price"]',
        'strong[class*="price"]',
    ):
        try:
            nodes = await a_el.query_selector_all(sel)
            for n in nodes:
                txt = (await n.inner_text() or "").strip()
                v = await _price_from_text(txt)
                if DEBUG: _log(f"[PRICE sel={sel} '{txt}'] -> {v}")
                if v >= 0.01:
                    return v
        except Exception:
            continue
    try:
        block = (await a_el.inner_text() or "").strip()
    except Exception:
        block = ""
    v = await _price_from_text(block)
    if DEBUG: _log(f"[PRICE block='{block}'] -> {v}")
    return v or 0.0

# ---- Flags ----
async def _flags_from_anchor(a_el: ElementHandle) -> Dict[str, bool]:
    shipping = False
    reserved = False
    try:
        if await a_el.query_selector('wallapop-badge[badge-type="shippingAvailable"]'):
            shipping = True
        if await a_el.query_selector('wallapop-badge[badge-type="reserved"]'):
            reserved = True
    except Exception:
        pass
    return {"shipping": shipping, "reserved": reserved}

# ---- Extract items ----
async def _extract_cards(page: Page) -> List[dict]:
    anchors = await page.query_selector_all('a[href^="/item/"]')
    items: List[dict] = []
    seen_ids = set()

    for a in anchors:
        href = await a.get_attribute("href") or ""
        if not href.startswith("/item/"):
            continue
        m = re.search(r"/item/([^/?#]+)", href)
        item_id = m.group(1) if m else re.sub(r"\W+", "", href)[:32]
        if not item_id or item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        url = WALLA_HTML_BASE + href
        title = (await a.get_attribute("title")) or (await a.get_attribute("aria-label")) or "Sin título"
        price = await _price_from_anchor(a)
        flags = await _flags_from_anchor(a)

        items.append({
            "id": item_id,
            "title": title.strip(),
            "price": price,
            "url": url,
            "seller_id": "",
            "shipping": flags["shipping"],
            "reserved": flags["reserved"],
            "sold": False,
        })

    return items

async def _light_scroll(page: Page):
    try:
        for y in (600, 1200, 1800):
            await page.evaluate(f"window.scrollTo(0, {y});")
            await page.wait_for_timeout(180)
        await page.evaluate("window.scrollTo(0, 0);")
        await page.wait_for_timeout(120)
    except Exception:
        pass

# ===========================
# API pública
# ===========================
async def search_items(query: str, filters: Optional[Dict[str, Any]] = None) -> List[WItem]:
    filters = filters or {}
    url = _build_search_url(query, filters)
    _log(f"[WALLA] URL: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
        context = await browser.new_context(
            user_agent=os.getenv("WALLA_UA", UA_DEFAULT),
            locale="es-ES",
        )
        if WALLA_BLOCK_RESOURCES:
            await context.route("**/*", _block_heavy_resources)

        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=WALLA_TIMEOUT_MS)
        except Exception as e:
            _log(f"[WALLA] ERROR al cargar: {e}")
            await browser.close()
            return []

        try:
            await _dismiss_cookies(page)
        except Exception:
            pass

        try:
            await page.wait_for_selector('a[href^="/item/"]', timeout=3000)
        except PWTimeout:
            pass

        await _light_scroll(page)
        raw_items = await _extract_cards(page)
        await browser.close()

    _log(f"[WALLA] Items crudos: {len(raw_items)}")
    if not raw_items:
        print(f"[WALLA/DOM] 0 items (query='{query}')")
        return []

    # --- Aplicar filtros ---
    strict_mode = filters.get("strict", True)
    raw_items = [it for it in raw_items if _title_matches_query(it["title"], query, strict=strict_mode)]
    _log(f"[WALLA] Items tras filtro título ({'estricto' if strict_mode else 'flexible'}): {len(raw_items)}")

    raw_items = [it for it in raw_items if not it.get("reserved")]
    _log(f"[WALLA] Tras excluir reservados: {len(raw_items)}")

    if "min" in filters:
        raw_items = [it for it in raw_items if it["price"] >= float(filters["min"])]
        _log(f"[WALLA] Tras min {filters['min']}: {len(raw_items)}")
    if "max" in filters:
        raw_items = [it for it in raw_items if it["price"] <= float(filters["max"])]
        _log(f"[WALLA] Tras max {filters['max']}: {len(raw_items)}")
    if filters.get("shipping"):
        raw_items = [it for it in raw_items if it["shipping"]]
        _log(f"[WALLA] Tras shipping=True: {len(raw_items)}")

    if filters.get("omit"):
        omit_words = filters["omit"]
        raw_items = [it for it in raw_items if not _contains_omit(it["title"], omit_words)]
        _log(f"[WALLA] Tras omitir palabras {omit_words}: {len(raw_items)}")

    try:
        raw_items.sort(key=lambda it: _score_title(it["title"], query), reverse=True)
    except Exception:
        pass

    items = [WItem(
        id=it["id"],
        title=it["title"],
        price=it["price"],
        url=it["url"],
        seller_id="",
        reserved=it.get("reserved", False),
        sold=it.get("sold", False),
        shipping=it.get("shipping", False),
    ) for it in raw_items[:MAX_ITEMS]]

    _log(f"[WALLA] Devolviendo {len(items)} items")
    return items

# ===========================
# Fallback FAKE
# ===========================
_fake_counter = 0
def search_items_fake(query: str) -> List[WItem]:
    global _fake_counter
    _fake_counter += 1
    if _fake_counter % 3 != 0:
        return []
    now = int(os.getenv("FAKE_NOW_TS", "0")) or __import__("time").time().__int__()
    rid = random.randint(1000, 9999)
    return [
        WItem(
            id=f"fake-{now}-{rid}",
            title=f"{query} demo #{_fake_counter}",
            price=random.choice([5.0, 10.5, 25.99, 60.0, 120.75]),
            url=f"{WALLA_HTML_BASE}/item/fake-{now}-{rid}",
            seller_id="",
            shipping=random.choice([True, False]),
        )
    ]
