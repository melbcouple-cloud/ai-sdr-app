# scanner.py — 4-Strategy Anti-Bot Scanner with status signals + Playwright deep scan
import re, sys, asyncio, threading, traceback, requests
from bs4 import BeautifulSoup

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

STEALTH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1", "Cache-Control": "max-age=0",
}

DOWNLOAD_EXTS = [".pdf",".zip",".doc",".docx",".ppt",".pptx",".xls",".xlsx",".csv",".mp4",".mp3"]

COOKIE_SELECTORS = [
    "#onetrust-accept-btn-handler","#accept-cookies",".cookie-accept",
    ".optanon-allow-all","#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    ".js-accept-cookies","#btn-cookie-allow",".cc-btn.cc-allow",
    "#cookie-accept",".cookie-consent-accept",
    "button[aria-label*='Accept']","button[aria-label*='accept']",
    "[data-testid='cookie-accept']",".gdpr-accept","#gdpr-consent-accept",
]

STEALTH_JS = (
    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
    "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
    "window.chrome={runtime:{},loadTimes:function(){},csi:function(){},app:{}};"
    "delete navigator.__proto__.webdriver;"
)

CTA_TRIGGER_KEYWORDS = [
    "register","sign up","signup","schedule","hcp login","prescribers",
    "request","get started","enroll","book","talk to a doctor",
    "find a doctor","patient support","contact us","free trial",
]


def _make_result(rows=None, status="ok", message=""):
    return {"rows": rows or [], "status": status, "message": message}


def _is_blocked(html):
    if not html or len(html.strip()) < 300:
        return True
    lower = html.lower()
    for s in ["just a moment","checking your browser","cf-browser-verification",
              "ddos-guard","enable javascript and cookies","access denied",
              "403 forbidden","request unsuccessful","incapsula incident",
              "ray id","_iuam","challenge-platform","please wait","security check"]:
        if s in lower:
            return True
    soup = BeautifulSoup(html, "html.parser")
    return len(soup.find_all("a", href=True)) < 3


def fingerprint(html, url):
    h = html.lower() if html else ""
    return {
        "is_spa":       bool(re.search(r"__NEXT_DATA__|window\.__nuxt|<div id=['\"]app['\"]>", html or "")),
        "is_wordpress": "wp-content" in h,
        "is_cloudflare": "cf-ray" in h or "__cf_bm" in h,
        "has_hubspot":  "hs-form" in h or "hubspot" in h,
        "has_marketo":  "marketo" in h or "mktdform" in h,
        "has_veeva":    "veeva" in h,
        "has_isi":      any(k in h for k in ["important safety","full prescribing","adverse reactions"]),
        "is_pharma":    any(k in h for k in ["prescribing information","indication","clinical trial"]),
    }


def _guess_form_purpose(form_id, action, text):
    c = (form_id + " " + action + " " + text).lower()
    if any(k in c for k in ["search","query"]):              return "site_search"
    if any(k in c for k in ["login","sign-in","signin"]):    return "login"
    if any(k in c for k in ["register","signup","sign-up"]): return "registration"
    if any(k in c for k in ["subscribe","newsletter"]):      return "newsletter"
    if any(k in c for k in ["contact","enquiry","inquiry"]): return "contact"
    if any(k in c for k in ["checkout","payment","order"]):  return "checkout"
    return "lead_generation"


def _extract_from_html(html, base_url, source):
    elements = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        for i, form in enumerate(soup.find_all("form"), 1):
            fid     = form.get("id") or form.get("name") or f"form_{i}"
            purpose = _guess_form_purpose(fid, form.get("action") or "", form.get_text())
            elements.append({"type":"form","text":"form_submit","form_id":fid,"purpose":purpose,"source":source})
            for inp in form.find_all(["input","select","textarea"]):
                if inp.get("type","text") in ("hidden","submit","button","image","reset"):
                    continue
                label = (inp.get("name") or inp.get("placeholder") or
                         inp.get("aria-label") or inp.get("id") or inp.get("type","text"))
                elements.append({"type":"form_field","text":label,
                                  "field_type":inp.get("type","text"),"form_id":fid,"source":source})

        # iframe-embedded forms (HubSpot / Marketo / Eloqua / Pardot)
        for iframe in soup.find_all("iframe"):
            isrc = iframe.get("src","") or iframe.get("data-src","")
            if any(k in isrc.lower() for k in ["hubspot","marketo","eloqua","pardot"]):
                nearby = iframe.find_previous(["h2","h3","h4"])
                fname  = nearby.get_text(strip=True)[:50] if nearby else "embedded_form"
                elements.append({"type":"form","text":fname,
                                  "form_id":f"iframe_{fname[:20]}",
                                  "purpose":"lead_generation","source":f"{source}_iframe"})

        for btn in soup.find_all("button"):
            txt = btn.get_text(strip=True)
            if txt and len(txt) < 120:
                elements.append({"type":"button","text":txt,"source":source})

        for a in soup.find_all("a", href=True):
            txt  = a.get_text(strip=True)
            href = a["href"]
            if not href or href.startswith("javascript") or href.strip() == "#":
                continue
            href_clean = href.split("#")[0]
            if any(ext in href_clean.lower() for ext in DOWNLOAD_EXTS):
                href = href_clean
            if any(ext in href.lower() for ext in DOWNLOAD_EXTS):
                elements.append({"type":"download","text":txt or href.split("/")[-1],"href":href,"source":source})
            elif txt:
                is_ext = href.startswith("http") and base_url not in href
                elements.append({"type":"external_link" if is_ext else "link","text":txt,"href":href,"source":source})

        # Videos — check data-src for lazy-loaded embeds (FIX for Issue #2)
        for vid in soup.find_all("video"):
            src = vid.get("src") or vid.get("data-src") or "video"
            elements.append({"type":"video","text":src.split("/")[-1][:60],"source":source})
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src","") or iframe.get("data-src","")
            if any(v in src for v in ["youtube","youtu.be","vimeo","wistia","brightcove"]):
                elements.append({"type":"video","text":"embedded_video:"+src[:80],"source":source})

    except Exception:
        traceback.print_exc()
    return elements


def _extract_nextjs(html, base_url, source):
    import json as _json
    elements = []
    try:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            return elements
        data = _json.loads(m.group(1))
        text = _json.dumps(data)
        for url in re.findall(r'"(https?://[^"]{5,200})"', text):
            if any(ext in url.lower() for ext in DOWNLOAD_EXTS):
                elements.append({"type":"download","text":url.split("/")[-1],"href":url,"source":source})
            elif base_url not in url:
                elements.append({"type":"external_link","text":url[:60],"href":url,"source":source})
    except Exception:
        pass
    return elements


def scan_page(url, page_name="Page"):
    """Tier-1 fast scan. Returns dict with rows, status, message."""
    html = None
    try:
        from curl_cffi import requests as cr
        r = cr.get(url, impersonate="chrome110", timeout=20)
        if r.status_code == 200:
            html = r.text
    except Exception:
        pass
    if not html:
        try:
            r = requests.get(url, timeout=15, headers=STEALTH_HEADERS)
            if r.status_code == 200:
                html = r.text
        except Exception as e:
            return _make_result(status="error", message=str(e))
    if not html:
        return _make_result(status="error", message="Could not fetch page.")
    if _is_blocked(html):
        return _make_result(status="blocked",
                            message="Bot protection detected. Use Deep Scan (Playwright) mode.")
    fp       = fingerprint(html, url)
    elements = _extract_from_html(html, url, "tier1")
    if fp["is_spa"]:
        elements += _extract_nextjs(html, url, "nextjs")
    status, message = "ok", ""
    if fp["is_spa"] and not elements:
        status, message = "js_required", "React/Next.js SPA detected. Try Deep Scan."
    elif fp["has_hubspot"] or fp["has_marketo"]:
        status, message = "partial", "HubSpot/Marketo forms detected — use Deep Scan for full extraction."
    return _make_result(rows=elements, status=status, message=message)


async def _playwright_scan_async(url):
    from playwright.async_api import async_playwright
    html_parts = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled","--no-sandbox","--disable-dev-shm-usage"],
            )
            ctx  = await browser.new_context(
                user_agent=STEALTH_HEADERS["User-Agent"],
                viewport={"width":1280,"height":900},
                java_script_enabled=True,
            )
            page = await ctx.new_page()
            await page.add_init_script(STEALTH_JS)
            await page.goto(url, wait_until="networkidle", timeout=30000)

            for sel in COOKIE_SELECTORS:
                try:
                    await page.click(sel, timeout=1500)
                    await page.wait_for_timeout(800)
                    break
                except Exception:
                    pass

            for _ in range(6):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(500)
            await page.evaluate("window.scrollTo(0,0)")
            html_parts.append(await page.content())

            for trigger in CTA_TRIGGER_KEYWORDS:
                try:
                    els = await page.locator(f"text=/{trigger}/i").all()
                    for el in els[:2]:
                        try:
                            await el.click(timeout=2000)
                            await page.wait_for_timeout(1000)
                            html_parts.append(await page.content())
                            await page.keyboard.press("Escape")
                            await page.wait_for_timeout(400)
                        except Exception:
                            pass
                except Exception:
                    pass
            await browser.close()
    except Exception as e:
        return None, str(e)
    return "\n".join(html_parts), ""


def scan_page_deep(url, page_name="Page"):
    """Tier-2 Playwright deep scan. Same return format as scan_page()."""
    combined_html, error_msg = None, ""

    def _run():
        nonlocal combined_html, error_msg
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            combined_html, error_msg = loop.run_until_complete(_playwright_scan_async(url))
        finally:
            loop.close()

    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=90)

    if not combined_html:
        return _make_result(status="error", message=error_msg or "Playwright scan timed out.")
    if _is_blocked(combined_html):
        return _make_result(status="blocked",
                            message="Still blocked with Playwright. Site may require login or VPN.")
    elements = _extract_from_html(combined_html, url, "playwright")
    return _make_result(rows=elements, status="ok",
                        message=f"Deep scan complete. {len(elements)} elements found.")
