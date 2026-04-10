# scanner.py — 4-Strategy Anti-Bot Scanner
import re
import sys
import asyncio
import threading
import traceback
import requests
from bs4 import BeautifulSoup

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

STEALTH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

DOWNLOAD_EXTS = [
    ".pdf", ".zip", ".doc", ".docx", ".ppt", ".pptx",
    ".xls", ".xlsx", ".csv", ".mp4", ".mp3"
]

COOKIE_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "#accept-cookies",
    ".cookie-accept",
    ".optanon-allow-all",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    ".js-accept-cookies",
    "#btn-cookie-allow",
    ".cc-btn.cc-allow",
    "#cookie-accept",
    ".cookie-consent-accept",
]

STEALTH_JS = "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };delete navigator.__proto__.webdriver;"


def _is_blocked(html):
    if not html or len(html.strip()) < 300:
        return True
    lower = html.lower()
    for s in [
        "just a moment", "checking your browser", "cf-browser-verification",
        "ddos-guard", "enable javascript and cookies", "access denied",
        "403 forbidden", "request unsuccessful", "incapsula incident",
        "ray id", "_iuam", "challenge-platform", "please wait",
        "security check"
    ]:
        if s in lower:
            return True
    soup = BeautifulSoup(html, "html.parser")
    return len(soup.find_all("a", href=True)) < 3


def _guess_form_purpose(form_id, action, text):
    c = (form_id + " " + action + " " + text).lower()
    if any(k in c for k in ["search", "query"]):                return "site_search"
    if any(k in c for k in ["login", "sign-in", "signin"]):    return "login"
    if any(k in c for k in ["register", "signup", "sign-up"]): return "registration"
    if any(k in c for k in ["subscribe", "newsletter"]):       return "newsletter"
    if any(k in c for k in ["contact", "enquiry", "inquiry"]): return "contact"
    if any(k in c for k in ["checkout", "payment", "order"]):  return "checkout"
    return "lead_generation"


def _extract_from_html(html, base_url, source):
    elements = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for i, form in enumerate(soup.find_all("form"), 1):
            fid     = form.get("id") or form.get("name") or f"form_{i}"
            purpose = _guess_form_purpose(fid, form.get("action") or "", form.get_text())
            elements.append({"type": "form", "text": "form_submit", "form_id": fid, "purpose": purpose, "source": source})
            for inp in form.find_all(["input", "select", "textarea"]):
                if inp.get("type", "text") in ("hidden", "submit", "button", "image", "reset"):
                    continue
                label = (inp.get("name") or inp.get("placeholder") or
                         inp.get("aria-label") or inp.get("id") or inp.get("type", "text"))
                elements.append({"type": "form_field", "text": label, "field_type": inp.get("type", "text"), "form_id": fid, "source": source})
        for btn in soup.find_all("button"):
            txt = btn.get_text(strip=True)
            if txt and len(txt) < 120:
                elements.append({"type": "button", "text": txt, "source": source})
        for a in soup.find_all("a", href=True):
            txt  = a.get_text(strip=True)
            href = a["href"]
            if not href or href.startswith("javascript") or href.strip() == "#":
                continue
            href_clean = href.split("#")[0]  # strip #page=X anchors
            if any(ext in href_clean.lower() for ext in DOWNLOAD_EXTS):
                href = href_clean
            if any(ext in href.lower() for ext in DOWNLOAD_EXTS):
                elements.append({"type": "download", "text": txt or href.split("/")[-1], "href": href, "source": source})
            elif txt:
                is_ext = href.startswith("http") and base_url not in href
                elements.append({"type": "external_link" if is_ext else "link", "text": txt, "href": href, "source": source})
        for vid in soup.find_all("video"):
            src = vid.get("src") or "video"
            elements.append({"type": "video", "text": src.split("/")[-1][:60], "source": source})
        for iframe in soup.find_all("iframe", src=True):
            src = iframe["src"]
            if any(v in src for v in ["youtube", "vimeo", "wistia", "brightcove"]):
                elements.append({"type": "video", "text": "embedded_video:" + src[:80], "source": source})
    except Exception:
        traceback.print_exc()
    return elements


def _extract_nextjs(html, base_url, source):
    import json
    elements = []
    try:
        m = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            return elements
        def walk(obj, d=0):
            if d > 10:
                return
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("href", "url", "path", "slug") and isinstance(v, str) and v.startswith("/"):
                        elements.append({"type": "link", "text": v.replace("/", " ").strip() or v, "href": v, "source": source})
                    else:
                        walk(v, d + 1)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item, d + 1)
        walk(json.loads(m.group(1)))
    except Exception:
        pass
    return elements


def _deduplicate(elements):
    seen, result = set(), []
    for e in elements:
        k = (e.get("type"), e.get("text", "")[:80])
        if k not in seen:
            seen.add(k)
            result.append(e)
    return result


# ── Strategy 1: curl_cffi ─────────────────────────────────────

def _scan_with_curl_cffi(url, base_url):
    print("[Strategy 1 curl_cffi] Trying: " + url)
    try:
        from curl_cffi.requests import Session as CurlSession
        session = CurlSession(impersonate="chrome136")
        r = session.get(url, timeout=25, allow_redirects=True)
        print(f"[Strategy 1] Status: {r.status_code}, length: {len(r.text)}")
        if r.status_code == 200 and not _is_blocked(r.text):
            elements = _extract_from_html(r.text, base_url, "curl_cffi")
            elements += _extract_nextjs(r.text, base_url, "curl_cffi")
            print(f"[Strategy 1] Found {len(elements)} elements")
            return elements
        print("[Strategy 1] Blocked or empty")
    except ImportError:
        print("[Strategy 1] curl_cffi not installed. Run: pip install curl_cffi")
    except Exception:
        traceback.print_exc()
    return []


# ── Strategy 2: plain requests ────────────────────────────────

def _scan_with_requests(url, base_url):
    print("[Strategy 2 requests] Trying: " + url)
    try:
        s = requests.Session()
        s.headers.update(STEALTH_HEADERS)
        r = s.get(url, timeout=20, allow_redirects=True)
        print(f"[Strategy 2] Status: {r.status_code}, length: {len(r.text)}")
        if r.status_code != 200:
            return []
        if _is_blocked(r.text):
            njs = _extract_nextjs(r.text, base_url, "requests")
            if njs:
                return njs
            print("[Strategy 2] Blocked")
            return []
        elements = _extract_from_html(r.text, base_url, "requests")
        elements += _extract_nextjs(r.text, base_url, "requests")
        print(f"[Strategy 2] Found {len(elements)} elements")
        return elements
    except Exception:
        traceback.print_exc()
        return []


# ── Strategy 3: Playwright ────────────────────────────────────

def _dismiss_cookies(page):
    for sel in COOKIE_SELECTORS:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(1500)
                return
        except Exception:
            pass
    try:
        for btn in page.query_selector_all("button"):
            txt = (btn.inner_text() or "").lower()
            if any(k in txt for k in ["accept", "agree", "allow", "got it", "ok"]):
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1500)
                    return
    except Exception:
        pass


def _pw_worker(url, base_url, warnings, result):
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTO
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--window-size=1440,900",
                ]
            )
            ctx = browser.new_context(
                extra_http_headers=STEALTH_HEADERS,
                viewport={"width": 1440, "height": 900},
                java_script_enabled=True,
                ignore_https_errors=True,
                locale="en-US",
                timezone_id="America/New_York",
            )
            page = ctx.new_page()
            page.add_init_script(STEALTH_JS)
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
            except PwTO:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    print(f"[Playwright] Navigation failed: {e}")
                    browser.close()
                    return
            page.wait_for_timeout(4000)
            _dismiss_cookies(page)
            page.wait_for_timeout(2000)
            try:
                total = page.evaluate("document.body.scrollHeight")
                step  = max(300, total // 8)
                for pos in range(0, total, step):
                    page.evaluate(f"window.scrollTo(0, {pos})")
                    page.wait_for_timeout(150)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(500)
            except Exception:
                pass
            html = page.evaluate("document.documentElement.outerHTML")
            print(f"[Playwright] HTML length: {len(html)}")
            if _is_blocked(html):
                print("[Playwright] Still blocked")
                browser.close()
                warnings.append("Playwright: page is bot-protected. Try ScraperAPI key or Manual Entry.")
                return
            elements = _extract_from_html(html, base_url, "playwright")
            elements += _extract_nextjs(html, base_url, "playwright")
            for iframe_el in page.query_selector_all("iframe"):
                try:
                    frame = iframe_el.content_frame()
                    if frame:
                        elements += _extract_from_html(
                            frame.evaluate("document.documentElement.outerHTML"),
                            base_url, "iframe"
                        )
                except Exception:
                    pass
            cta_kw = ["register", "sign up", "subscribe", "get started", "enroll", "join", "request"]
            triggered = 0
            for el in page.query_selector_all("button, a[role=button]"):
                if triggered >= 3:
                    break
                try:
                    txt  = (el.inner_text() or "").lower().strip()
                    href = el.get_attribute("href") or ""
                    if any(k in txt for k in cta_kw):
                        if not (href and href.startswith("http")) and el.is_visible():
                            el.click()
                            page.wait_for_timeout(3000)
                            new_html = page.evaluate("document.documentElement.outerHTML")
                            new_els  = _extract_from_html(new_html, base_url, "post_cta")
                            existing = {(e["type"], e["text"]) for e in elements}
                            elements += [ne for ne in new_els if (ne["type"], ne["text"]) not in existing]
                            triggered += 1
                except Exception:
                    pass
            browser.close()
            result.extend(elements)
    except Exception:
        print("[Playwright Worker] EXCEPTION:")
        traceback.print_exc()
    finally:
        try:
            loop.close()
        except Exception:
            pass


def _scan_with_playwright(url, base_url, warnings):
    print("[Strategy 3 Playwright] Launching: " + url)
    result = []
    t = threading.Thread(target=_pw_worker, args=(url, base_url, warnings, result), daemon=True)
    t.start()
    t.join(timeout=120)
    if t.is_alive():
        warnings.append("Playwright timed out after 120s.")
    print(f"[Strategy 3] Elements: {len(result)}")
    return result


# ── Strategy 4: ScraperAPI ────────────────────────────────────

def _scan_with_scraperapi(url, base_url, api_key):
    print("[Strategy 4 ScraperAPI] Trying: " + url)
    try:
        import urllib3
        urllib3.disable_warnings()
        proxy_url = f"http://scraperapi:{api_key}@proxy-server.scraperapi.com:8001"
        s = requests.Session()
        s.headers.update(STEALTH_HEADERS)
        s.proxies = {"http": proxy_url, "https": proxy_url}
        s.verify  = False
        r = s.get(url, timeout=60, allow_redirects=True)
        print(f"[Strategy 4] Status: {r.status_code}, length: {len(r.text)}")
        if r.status_code == 200 and not _is_blocked(r.text):
            elements = _extract_from_html(r.text, base_url, "scraperapi")
            elements += _extract_nextjs(r.text, base_url, "scraperapi")
            print(f"[Strategy 4] Found {len(elements)} elements")
            return elements
        print("[Strategy 4] Blocked or bad status")
    except Exception:
        traceback.print_exc()
    return []


# ── Strategy 5: Google Cache ──────────────────────────────────

def _scan_google_cache(url, base_url):
    print("[Strategy 5 Google Cache] Trying: " + url)
    try:
        s = requests.Session()
        s.headers.update(STEALTH_HEADERS)
        r = s.get("https://webcache.googleusercontent.com/search?q=cache:" + url, timeout=15)
        print(f"[Strategy 5] Status: {r.status_code}, length: {len(r.text)}")
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup.find_all(["script", "style", "noscript"]):
            tag.decompose()
        links = soup.find_all("a", href=True)
        if len(links) < 2:
            return []
        elements = _extract_from_html(str(soup), base_url, "google_cache")
        elements += _extract_nextjs(r.text, base_url, "google_cache")
        print(f"[Strategy 5] Found {len(elements)} elements")
        return elements
    except Exception:
        traceback.print_exc()
        return []


# ── Public API ────────────────────────────────────────────────

def scan_website(url, options=None):
    options  = options or {}
    result   = {"elements": [], "warnings": [], "meta": {}}
    warnings = result["warnings"]
    scraper_api_key = options.get("scraper_api_key", "").strip()

    if not url.startswith("http"):
        url = "https://" + url
    base_url = url.split("/")[2].split("@")[-1] if "//" in url else url

    print("\n" + "="*60)
    print("SCANNING: " + url)
    print("Base: " + base_url)
    print("="*60)

    elements = _scan_with_curl_cffi(url, base_url)
    strategy = "curl_cffi"

    if len(elements) < 5:
        warnings.append("curl_cffi returned little — trying plain requests...")
        elements = _scan_with_requests(url, base_url)
        strategy = "requests"

    if len(elements) < 5:
        warnings.append("Plain requests blocked — launching browser (Playwright)...")
        elements = _scan_with_playwright(url, base_url, warnings)
        strategy = "playwright"

    if len(elements) < 5 and scraper_api_key:
        warnings.append("Playwright blocked — trying ScraperAPI...")
        elements = _scan_with_scraperapi(url, base_url, scraper_api_key)
        strategy = "scraperapi"

    if len(elements) < 5:
        warnings.append("Trying Google Cache as last resort...")
        elements = _scan_google_cache(url, base_url)
        strategy = "google_cache"

    if len(elements) < 5:
        warnings.append(
            "All 5 strategies returned minimal results. "
            "This site uses enterprise bot protection (Incapsula/Cloudflare). "
            "Add a ScraperAPI key in the sidebar OR use the Manual Entry tab to build the SDR."
        )

    print(f"\nFINAL: {len(elements)} elements | strategy={strategy}")
    result["elements"]              = _deduplicate(elements)
    result["meta"]["strategy_used"] = strategy
    result["meta"]["forms_found"]   = sum(1 for e in result["elements"] if e["type"] == "form")
    result["meta"]["cta_triggered"] = []
    return result


# ── Multi-page scan ───────────────────────────────────────────

def scan_multiple_urls(urls, options=None):
    options  = options or {}
    all_elements = []
    all_warnings = []
    all_meta     = {}
    strategies_used = []

    for url in urls:
        url = url.strip()
        if not url:
            continue
        result = scan_website(url, options)
        # Tag each element with the page it came from
        for el in result["elements"]:
            el["page_url"] = url
        all_elements.extend(result["elements"])
        all_warnings.extend([f"[{url}] {w}" for w in result["warnings"]])
        strategies_used.append(result["meta"].get("strategy_used", "unknown"))

    # Global dedup across all pages
    seen, deduped = set(), []
    for e in all_elements:
        k = (e.get("type"), e.get("text", "")[:80])
        if k not in seen:
            seen.add(k)
            deduped.append(e)

    return {
        "elements": deduped,
        "warnings": all_warnings,
        "meta": {
            "strategy_used":  ", ".join(set(strategies_used)),
            "forms_found":    sum(1 for e in deduped if e["type"] == "form"),
            "pages_scanned":  len([u for u in urls if u.strip()]),
            "cta_triggered":  [],
        }
    }
