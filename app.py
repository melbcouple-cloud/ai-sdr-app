import hmac, os, re
import streamlit as st
import pandas as pd
from io import BytesIO
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# PASSWORD
def check_password():
    def _entered():
        try:
            correct = st.secrets.get("APP_PASSWORD", "")
        except Exception:
            correct = os.environ.get("APP_PASSWORD", "")
        if correct and hmac.compare_digest(st.session_state["pw"], correct):
            st.session_state["auth"] = True
            del st.session_state["pw"]
        else:
            st.session_state["auth"] = False
    if st.session_state.get("auth"):
        return True
    st.markdown("## SDR Generator")
    st.text_input("Password", type="password", on_change=_entered, key="pw")
    if st.session_state.get("auth") == False:
        st.error("Incorrect password.")
    return False

_pw = False
try:
    _pw = bool(st.secrets.get("APP_PASSWORD", ""))
except Exception:
    _pw = bool(os.environ.get("APP_PASSWORD", ""))
if _pw and not check_password():
    st.stop()

# HELPERS
def slug(t):
    return re.sub(r"[^a-z0-9]+", "_", t.lower().strip()).strip("_")

PHARMA_KEYWORDS = {
    "isi":         ["isi_scroll_25","isi_scroll_50","isi_scroll_75","isi_scroll_100"],
    "safety":      ["isi_scroll_25","isi_scroll_50","isi_scroll_75","isi_scroll_100"],
    "prescribing": ["download_click_prescribing_information"],
    "hcp":         ["form_begins","form_success","link_click_hcp_portal"],
    "register":    ["form_begins","form_success","form_error","form_abandoned"],
    "resource":    ["download_click_pdf","link_click_resource"],
    "video":       ["video_begins","video_progression_25","video_progression_50","video_progression_75","video_ends"],
    "copay":       ["link_click_copay_card","form_begins_copay","form_success_copay"],
    "find":        ["link_click_find_a_doctor","link_click_find_a_pharmacy"],
    "support":     ["link_click_patient_support","form_begins_support"],
    "contact":     ["exit_click_contact_us"],
    "about":       ["link_click_about"],
    "home":        ["scroll_percentage"],
}

STANDARD_EVENTS = [
    ("header",  "navigation",        "link_click",  "<click_text>",   "Click URL",               "engagement"),
    ("footer",  "navigation",        "link_click",  "<click_text>",   "Click URL",               "engagement"),
    ("inpage",  "cta_clicks",        "link_click",  "page_url",       "<click_text>",            "engagement"),
    ("scroll",  "scroll_percentage", "scroll",      "page_url",       "25% | 50% | 75% | 100%",  "engagement"),
    ("exit",    "exit_click",        "click",       "exit_link_text", "exit_destination_url",    "exit"),
]

def infer_events(page_name, page_url, site_type, ga_counter):
    """Generate SDR rows for a page."""
    rows = []
    name_lower = (page_name + page_url).lower()
    for loc, cat, action, label, dest, intent in STANDARD_EVENTS:
        rows.append({
            "Page":            page_name,
            "Category":        cat,
            "Event Name":      f"{action}_{slug(page_name)}_{loc}" if loc not in ("scroll","exit") else ("scroll_percentage" if loc=="scroll" else "exit_click"),
            "Action":          action,
            "Label":           label,
            "CTA Location":    loc,
            "CTA Text":        dest,
            "Business Intent": intent,
            "Page URL":        page_url,
            "Event ID":        f"ga{ga_counter}",
        })
        ga_counter += 1
    matched = set()
    for kw, ev_list in PHARMA_KEYWORDS.items():
        if kw in name_lower:
            for ev in ev_list:
                if ev not in matched:
                    matched.add(ev)
                    cat = ev.split("_")[0] if "_" in ev else "inpage"
                    rows.append({
                        "Page":            page_name,
                        "Category":        cat,
                        "Event Name":      ev,
                        "Action":          ev.split("_")[0],
                        "Label":           "<value>",
                        "CTA Location":    "inpage",
                        "CTA Text":        "<click_text>",
                        "Business Intent": "consideration" if cat in ("video","download") else "conversion" if cat in ("form","copay") else "awareness" if "isi" in ev else "engagement",
                        "Page URL":        page_url,
                        "Event ID":        f"ga{ga_counter}",
                    })
                    ga_counter += 1
    if site_type == "HCP" and "hcp" in name_lower:
        for ev, intent in [("form_begins","acquisition"),("form_success","conversion"),("form_error","engagement"),("form_abandoned","engagement")]:
            rows.append({
                "Page": page_name, "Category": "form",
                "Event Name": f"{ev}_hcp_registration", "Action": ev,
                "Label": "hcp_registration_form", "CTA Location": "inpage",
                "CTA Text": "Register", "Business Intent": intent,
                "Page URL": page_url, "Event ID": f"ga{ga_counter}",
            })
            ga_counter += 1
    return rows, ga_counter

def build_excel(df, project_name):
    wb   = openpyxl.Workbook()
    hf   = PatternFill("solid", fgColor="1F4E79")
    hfnt = Font(color="FFFFFF", bold=True, size=10)
    af   = PatternFill("solid", fgColor="EBF3FB")
    thin = Side(style="thin", color="BFBFBF")
    bdr  = Border(left=thin, right=thin, top=thin, bottom=thin)
    ctr  = Alignment(horizontal="center", vertical="center", wrap_text=True)
    lft  = Alignment(horizontal="left",   vertical="center", wrap_text=True)

    def make_header(ws, cols, widths):
        ws.row_dimensions[1].height = 26
        for ci, (c, w) in enumerate(zip(cols, widths), 1):
            cell = ws.cell(row=1, column=ci, value=c)
            cell.fill = hf; cell.font = hfnt
            cell.alignment = ctr; cell.border = bdr
            ws.column_dimensions[get_column_letter(ci)].width = w

    def add_row(ws, vals, ri):
        fill = af if ri % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
        for ci, v in enumerate(vals, 1):
            cell = ws.cell(row=ri, column=ci, value=str(v) if v is not None else "")
            cell.fill = fill; cell.font = Font(size=9)
            cell.alignment = lft; cell.border = bdr

    ws1 = wb.active; ws1.title = 'SDR'
    make_header(ws1,
        ["No","Page","Category","Event Name","Action","Label","CTA Location","CTA Text","Business Intent","Page URL","Event ID"],
        [5,20,18,34,14,30,15,22,18,40,10])
    for ri, (_, row) in enumerate(df.iterrows(), 2):
        add_row(ws1, [ri-1, row.get("Page",""), row.get("Category",""), row.get("Event Name",""), row.get("Action",""), row.get("Label",""), row.get("CTA Location",""), row.get("CTA Text",""), row.get("Business Intent",""), row.get("Page URL",""), row.get("Event ID","")], ri)

    ws2 = wb.create_sheet('Link_Click')
    make_header(ws2,
        ["URL","event","event_name","cta_link","cta_location","cta_text","cta_type","current_page_url","screenshots"],
        [35,22,22,40,15,28,12,40,15])
    lc_df = df[df["Category"].isin(["navigation","cta_clicks","inpage","header","footer"])]
    for ri, (_, row) in enumerate(lc_df.iterrows(), 2):
        add_row(ws2, [row.get("Page URL",""), row.get("Event ID",""), row.get("Event Name",""), row.get("CTA Text",""), row.get("CTA Location",""), row.get("Label",""), "link", row.get("Page URL",""), ""], ri)

    ws3 = wb.create_sheet('Exit_Click')
    make_header(ws3,
        ["URL","event","event_name","exit_linkname","exit_url","exit_location","current_page_url","screenshots"],
        [35,22,22,30,42,15,40,15])
    ec_df = df[df["Category"]=="exit"]
    for ri, (_, row) in enumerate(ec_df.iterrows(), 2):
        add_row(ws3, [row.get("Page URL",""), row.get("Event ID",""), row.get("Event Name",""), row.get("CTA Text",""), row.get("Label",""), row.get("CTA Location",""), row.get("Page URL",""), ""], ri)

    ws4 = wb.create_sheet('Downloads')
    make_header(ws4,
        ["URL","event","event_name","file_text","file_type","file_url","file_location","current_page_url","screenshots"],
        [35,22,22,30,10,42,15,40,15])
    dl_df = df[df["Category"]=="download"]
    for ri, (_, row) in enumerate(dl_df.iterrows(), 2):
        add_row(ws4, [row.get("Page URL",""), row.get("Event ID",""), row.get("Event Name",""), row.get("CTA Text",""), "pdf", row.get("Label",""), row.get("CTA Location",""), row.get("Page URL",""), ""], ri)

    ws5 = wb.create_sheet('Forms')
    make_header(ws5,
        ["URL","GA4 Event (event)","GA4 Event (event_name)","form_title","form_info","current_page_url"],
        [35,25,25,30,48,40])
    fm_df = df[df["Category"]=="form"]
    for ri, (_, row) in enumerate(fm_df.iterrows(), 2):
        add_row(ws5, [row.get("Page URL",""), row.get("Event ID",""), row.get("Event Name",""), row.get("Label",""), row.get("CTA Text",""), row.get("Page URL","")], ri)

    ws6 = wb.create_sheet('Videos')
    make_header(ws6,
        ["URL","GA4_event","Video_name","Video_elapsed_time","Video_link","Video_source","current_page_url"],
        [35,28,30,20,42,12,40])
    vd_df = df[df["Category"]=="video"]
    for ri, (_, row) in enumerate(vd_df.iterrows(), 2):
        add_row(ws6, [row.get("Page URL",""), row.get("Event Name",""), row.get("Label",""), "", "", "html5", row.get("Page URL","")], ri)

    buf = BytesIO(); wb.save(buf); buf.seek(0)
    return buf

def quick_scan(url, page_name='Scanned'):
    from urllib.parse import urlparse, urljoin
    parsed = urlparse(url)
    # Extract credentials from URL if present (user:pass@host format)
    auth = None
    if parsed.username and parsed.password:
        auth = (parsed.username, parsed.password)
        port_part = f":{parsed.port}" if parsed.port else ""
        clean_url = parsed._replace(netloc=parsed.hostname + port_part).geturl()
    else:
        clean_url = url
    parsed = urlparse(clean_url)
    html = None
    try:
        from curl_cffi import requests as cr
        r = cr.get(clean_url, impersonate="chrome110", timeout=20, auth=auth)
        if r.status_code == 200:
            html = r.text
    except Exception:
        pass
    if not html:
        try:
            import requests
            r = requests.get(clean_url, timeout=15, auth=auth,
                headers={"User-Agent":"Mozilla/5.0 Chrome/120"})
            if r.status_code == 200:
                html = r.text
        except Exception:
            pass
    if not html:
        return []
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    rows = []
    dl_exts = {".pdf",".docx",".xlsx",".zip",".ppt",".pptx"}

    def detect_location(tag):
        """Walk up the DOM tree to detect header/footer/nav/hero/modal/sidebar/inpage."""
        for parent in tag.parents:
            if parent.name is None:
                continue
            tag_name = parent.name.lower()
            classes  = " ".join(parent.get("class", [])).lower()
            pid      = (parent.get("id") or "").lower()
            combined = f"{tag_name} {classes} {pid}"
            if tag_name == "header" or any(x in combined for x in ["header","site-header","navbar","nav-top","top-nav","masthead"]):
                return "header"
            if tag_name == "footer" or any(x in combined for x in ["footer","site-footer","footer-nav","foot-"]):
                return "footer"
            if tag_name == "nav" or any(x in combined for x in ["nav","navigation","main-nav","primary-nav","menu"]):
                return "header"
            if any(x in combined for x in ["hero","banner","jumbotron","splash","carousel"]):
                return "hero"
            if any(x in combined for x in ["modal","dialog","popup","overlay","lightbox"]):
                return "modal"
            if any(x in combined for x in ["sidebar","side-bar","aside","widget"]):
                return "sidebar"
        return "inpage"

    for a in soup.find_all('a', href=True):
        href = a.get('href','').strip()
        text = a.get_text(strip=True) or href
        if not text or len(text) < 2:
            continue
        full = urljoin(clean_url, href)
        fp   = urlparse(full)
        ext  = os.path.splitext(fp.path)[1].lower()
        loc  = detect_location(a)
        if ext in dl_exts:
            rows.append({"Page":page_name,"Category":"download","Event Name":f"download_click_{slug(text)[:30]}","Action":"click","Label":full,"CTA Location":loc,"CTA Text":text,"Business Intent":"consideration","Page URL":clean_url,"Event ID":""})
        elif fp.netloc and fp.netloc != parsed.netloc:
            rows.append({"Page":page_name,"Category":"exit","Event Name":f"exit_click_{slug(text)[:30]}","Action":"click","Label":full,"CTA Location":loc,"CTA Text":text,"Business Intent":"exit","Page URL":clean_url,"Event ID":""})
        elif href and not href.startswith('#') and not href.startswith('mailto'):
            rows.append({"Page":page_name,"Category":"navigation","Event Name":f"link_click_{slug(text)[:30]}","Action":"click","Label":full,"CTA Location":loc,"CTA Text":text,"Business Intent":"engagement","Page URL":clean_url,"Event ID":""})
    for frm in soup.find_all('form'):
        # smart form name detection
        _fid   = frm.get('id','') or frm.get('name','') or ''
        _faction = frm.get('action','') or ''
        _aria  = frm.get('aria-label','') or ''
        # look for nearby heading
        _nearby_h = ''
        for _tag in ['h1','h2','h3','legend']:
            _hel = frm.find(_tag) or (frm.find_previous(_tag))
            if _hel:
                _nearby_h = _hel.get_text(strip=True)[:40]
        # look for submit button text
        _submit_btn = frm.find('button', attrs={'type':'submit'}) or frm.find('input', attrs={'type':'submit'})
        _btn_text = ''
        if _submit_btn:
            _btn_text = (_submit_btn.get_text(strip=True) or _submit_btn.get('value',''))[:30]
        # pick best name: aria > nearby heading > form id > action path > submit btn > fallback
        if _aria:
            fname = _aria
        elif _nearby_h:
            fname = _nearby_h
        elif _fid:
            fname = _fid
        elif _faction and '/' in _faction:
            fname = _faction.rstrip('/').split('/')[-1]
        elif _btn_text:
            fname = _btn_text
        else:
            fname = 'form'
        if isinstance(fname, list): fname = '_'.join(fname)
        fname = str(fname).strip()
        loc = detect_location(frm)
        # Use page URL slug for clean event names (e.g. form_start_sign_up)
        _page_slug = clean_url.rstrip('/').split('/')[-1] or 'home'
        _page_slug = slug(_page_slug)[:20]
        for ev, intent in [('form_start', 'acquisition'), ('form_submit', 'conversion'),
                           ('form_error', 'engagement'), ('form_abandon', 'engagement')]:
            rows.append({"Page": page_name, "Category": "form",
                         "Event Name": f"{ev}_{_page_slug}",
                         "Action": ev, "Label": fname,
                         "CTA Location": loc, "CTA Text": _btn_text or fname,
                         "Business Intent": intent, "Page URL": clean_url, "Event ID": ""})
    for v in soup.find_all(['video','iframe']):
        src = v.get('src','') or v.get('data-src','')
        if 'vimeo' in src or 'youtube' in src or v.name=='video':
            # --- Video title: prefer iframe title attr, then nearby heading, then page name ---
            vname = v.get('title','').strip()
            if not vname or vname.startswith('http'):
                # look for closest heading BEFORE the iframe in the same container
                _vpar = v.find_parent(['section','article','div','figure'])
                if _vpar:
                    _vh = _vpar.find(['h1','h2','h3','h4'])
                    if _vh:
                        vname = _vh.get_text(strip=True)[:60]
            if not vname:
                vname = page_name

            # --- CTA Text: human-readable trigger label ---
            _cta_text = 'Watch video'

            # --- CTA Location: scan the WHOLE page for a play/watch trigger button ---
            # Strategy: look globally for buttons/links that could open this video
            # (play buttons are often outside the iframe container entirely)
            _vid_loc = None

            # 1. Check for any button/link in the page with play/watch/video class or text
            for _el in soup.find_all(['button', 'a']):
                _cls = ' '.join(_el.get('class', [])).lower()
                _lbl = _el.get('aria-label', '').lower()
                _txt = _el.get_text(strip=True).lower()
                _dat = ' '.join([
                    _el.get('data-target',''),
                    _el.get('data-video',''),
                    _el.get('data-src',''),
                    _el.get('data-modal',''),
                ]).lower()
                if any(kw in (_cls + _lbl + _txt + _dat)
                       for kw in ['play', 'watch', 'video', 'vimeo', 'youtube']):
                    _loc_candidate = detect_location(_el)
                    if _loc_candidate != 'modal':
                        _vid_loc = _loc_candidate
                        _cta_text = _el.get_text(strip=True) or 'Watch video'
                        if not _cta_text.strip():
                            _cta_text = _el.get('aria-label','Watch video') or 'Watch video'

            # 2. If no trigger found, use the section that contains the iframe
            if not _vid_loc:
                _outer = v.find_parent(['section', 'article', 'main'])
                while _outer:
                    _loc_candidate = detect_location(_outer)
                    if _loc_candidate != 'modal':
                        _vid_loc = _loc_candidate
                    _outer = _outer.find_parent(['section', 'article', 'main'])

            # 3. Final fallback
            if not _vid_loc:
                _vid_loc = 'body'
            _intent = 'engagement'
            for ev in ['video_start','video_progress_25','video_progress_50','video_progress_75','video_complete']:
                rows.append({"Page":page_name,"Category":"video","Event Name":ev,
                             "Action":"video","Label":vname,
                             "CTA Location":_vid_loc,"CTA Text":_cta_text,
                             "Business Intent":_intent,"Page URL":clean_url,"Event ID":""})
    return rows

# APP
st.set_page_config(page_title='SDR Generator', layout='wide')

for k,v in {'sdr_df':None,'ga_counter':4,'project_name':''}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Sidebar
with st.sidebar:
    st.markdown('### SDR Generator')
    st.caption('3-Step Tracking Plan Builder')
    st.divider()
    if st.session_state.sdr_df is not None and len(st.session_state.sdr_df) > 0:
        df_s = st.session_state.sdr_df
        st.metric('Total Events', len(df_s))
        for cat, grp in df_s.groupby('Category'):
            st.caption(f'{cat}: {len(grp)}')
        st.divider()
    if st.button('Start Over'):
        st.session_state.sdr_df = None
        st.session_state.ga_counter = 4
        st.rerun()

st.title('SDR Generator')
st.caption('Step 1: Define pages  |  Step 2: Review and edit  |  Step 3: Export Excel')
st.divider()

has_draft = st.session_state.sdr_df is not None and len(st.session_state.sdr_df) > 0

with st.expander('Step 1 - Project Setup and Page List', expanded=not has_draft):
    c1, c2 = st.columns(2)
    project_name = c1.text_input('Project / Brand Name', value=st.session_state.project_name, placeholder='e.g. Viewuvealdifferently')
    site_type    = c2.selectbox('Site Type', ['HCP', 'Patient', 'Corporate', 'General'])
    st.session_state.project_name = project_name

    st.markdown('**Paste your page list** (one per line as: Page Name | URL)')
    st.markdown('**Choose how to discover pages**')
    disc_tab1, disc_tab2, disc_tab3 = st.tabs(['🔍 Auto-Crawl', '🗺️ Sitemap URL', '📋 Paste URL List'])
    with disc_tab1:
        scan_url_input = st.text_input('Root URL (auto-discovers all pages)',
            placeholder='https://www.opzelura.com  or  https://user:pass@staging.example.com', key='crawl_url')
        st.caption('Crawls the site recursively up to depth 3. Best for most sites.')
    with disc_tab2:
        sitemap_url_input = st.text_input('Sitemap URL',
            placeholder='https://www.opzelura.com/sitemap.xml', key='sitemap_url')
        st.caption('Parses all URLs from sitemap XML. Fast — but may miss unlisted pages.')
    with disc_tab3:
        manual_url_list = st.text_area('Paste full URLs — one per line', height=160,
            placeholder='https://www.opzelura.com/\nhttps://www.opzelura.com/atopic-dermatitis/\nhttps://www.opzelura.com/vitiligo/',
            key='manual_urls')
        st.caption('Most accurate — paste the full list from your SEO/web team. 100% coverage guaranteed.')
    pages_input = st.text_area('Additional pages (Name | /path)', height=80,
        placeholder='Homepage | /\nHCP Page | /hcp', help='Extra pages not covered by discovery above.')

    if st.button('Generate Draft SDR', type='primary', use_container_width=True):
        all_rows = []
        ga = st.session_state.ga_counter

        # parse any manually added extra pages
        manual_pages = []
        if pages_input.strip():
            for line in pages_input.strip().splitlines():
                line = line.strip()
                if not line: continue
                if '|' in line:
                    parts = line.split('|', 1)
                    manual_pages.append((parts[0].strip(), parts[1].strip()))
                else:
                    manual_pages.append((line, f'/{slug(line)}'))

        _crawl_input   = st.session_state.get('crawl_url', '').strip().rstrip('/')
        _sitemap_input = st.session_state.get('sitemap_url', '').strip()
        _manual_input  = st.session_state.get('manual_urls', '').strip()

        base = _crawl_input or _sitemap_input or ''
        if not base and not _manual_input:
            st.warning('Please provide a URL in at least one discovery tab.')
            st.stop()
        if not base and _manual_input:
            from urllib.parse import urlparse as _up2
            _first = _manual_input.strip().splitlines()[0].strip()
            _p2 = _up2(_first)
            base = f'{_p2.scheme}://{_p2.netloc}'

        from urllib.parse import urlparse as _up
        import requests as _req
        from bs4 import BeautifulSoup as _BS

        _parsed    = _up(base)
        _auth_tup  = (_parsed.username, _parsed.password) if _parsed.username else None
        _netloc    = _parsed.hostname + (f':{_parsed.port}' if _parsed.port else '')
        _scheme    = _parsed.scheme
        _auth_pfx  = f'{_parsed.username}:{_parsed.password}@' if _parsed.username else ''

        def _make_url(path):
            p = path if path.startswith('/') else f'/{path}'
            return f'{_scheme}://{_auth_pfx}{_netloc}{p}'

        # --- Shared helper ---
        def _collect_links(html_text, _seen_set, _pnames, _netloc_str):
            from urllib.parse import urlparse as _up2
            _s = _BS(html_text, 'lxml')
            _found = []
            _cta_words = ['sign up','learn more','read more','click here','get started','discover','explore','view','see how','stay up']
            for _a in _s.find_all('a', href=True):
                _href = _a.get('href','').strip()
                _text = (_a.get('title','') or _a.get_text(strip=True) or '').strip()
                _ph = _up2(_href)
                if _ph.netloc and _ph.netloc != _netloc_str:
                    continue
                _path = _ph.path
                if (not _path or not _path.startswith('/') or _path.startswith('//')
                        or _path in _seen_set or '.' in _path.split('/')[-1] or len(_text) > 80):
                    continue
                if _text and 1 < len(_text) < 80:
                    _is_cta = any(c in _text.lower() for c in _cta_words)
                    if _path not in _pnames or not _is_cta:
                        if not _is_cta:
                            _pnames[_path] = _text[:60]
                        elif _path not in _pnames:
                            _pnames[_path] = _path.strip('/').replace('-',' ').replace('_',' ').title()
                _found.append(_path)
            return _found

        _seen       = set()
        scan_targets = []
        _page_names  = {}

        # ── METHOD 1: Manual URL list ──
        if _manual_input:
            with st.spinner('Loading pages from pasted URL list...'):
                from urllib.parse import urlparse as _up3
                for _u in [u.strip() for u in _manual_input.splitlines() if u.strip()]:
                    try:
                        _pu = _up3(_u)
                        if _pu.scheme and _pu.netloc:
                            _path = _pu.path or '/'
                            _name = _path.strip('/').replace('-',' ').replace('_',' ').title() or 'Homepage'
                            if _u not in [t[1] for t in scan_targets]:
                                scan_targets.append((_name[:60], _u))
                    except Exception:
                        pass
                st.success(f'✅ Loaded {len(scan_targets)} pages from pasted URL list')

        # ── METHOD 2: Sitemap XML ──
        elif _sitemap_input:
            with st.spinner(f'Parsing sitemap...'):
                try:
                    import xml.etree.ElementTree as _ET
                    _sr = _req.get(_sitemap_input, headers={'User-Agent':'Mozilla/5.0 Chrome/120'}, timeout=15)
                    _sr.raise_for_status()
                    _root_xml = _ET.fromstring(_sr.content)
                    _ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                    _all_locs = [l.text.strip() for l in _root_xml.findall('.//sm:loc', _ns)]
                    _final_urls = []
                    for _su in _all_locs:
                        if _su.endswith('.xml'):
                            try:
                                _cr = _req.get(_su, headers={'User-Agent':'Mozilla/5.0 Chrome/120'}, timeout=10)
                                _cr.raise_for_status()
                                _cr_root = _ET.fromstring(_cr.content)
                                for _cl in _cr_root.findall('.//sm:loc', _ns):
                                    _final_urls.append(_cl.text.strip())
                            except Exception:
                                _final_urls.append(_su)
                        else:
                            _final_urls.append(_su)
                    from urllib.parse import urlparse as _up4
                    for _u in _final_urls:
                        _pu = _up4(_u)
                        if _pu.netloc != _netloc:
                            continue
                        _path = _pu.path or '/'
                        _name = _path.strip('/').replace('-',' ').replace('_',' ').title() or 'Homepage'
                        if _u not in [t[1] for t in scan_targets]:
                            scan_targets.append((_name[:60], _u))
                    st.success(f'✅ Found {len(scan_targets)} pages in sitemap')
                except Exception as _se:
                    st.warning(f'Sitemap parse failed: {_se}. Switching to auto-crawl.')

        # ── METHOD 3: Auto-crawl ──
        if not scan_targets and _crawl_input:
            with st.spinner('Auto-discovering pages by crawling...'):
                try:
                    _resp = _req.get(_make_url('/'), auth=_auth_tup,
                                     headers={'User-Agent':'Mozilla/5.0 Chrome/120'}, timeout=15)
                    if _resp.status_code != 200:
                        st.error(f'Could not reach {base} — HTTP {_resp.status_code}')
                        st.stop()
                    scan_targets.append(('Homepage', _make_url('/')))
                    _seen.add('/')
                    _page_names['/'] = 'Homepage'
                    _pass1 = _collect_links(_resp.text, _seen, _page_names, _netloc)
                    _queue = []
                    for _p in _pass1:
                        if _p not in _seen:
                            _seen.add(_p)
                            _queue.append(_p)
                    _deep = []
                    for _qp in _queue[:30]:
                        try:
                            _r2 = _req.get(_make_url(_qp), auth=_auth_tup,
                                           headers={'User-Agent':'Mozilla/5.0 Chrome/120'}, timeout=10)
                            if _r2.status_code == 200:
                                for _sp in _collect_links(_r2.text, _seen, _page_names, _netloc):
                                    if _sp not in _seen:
                                        _seen.add(_sp)
                                        _deep.append(_sp)
                        except Exception:
                            pass
                    for _p in _queue + _deep:
                        _name = _page_names.get(_p, _p.strip('/').replace('-',' ').replace('_',' ').title() or _p)
                        scan_targets.append((_name[:60], _make_url(_p)))
                    st.success(f'✅ Auto-discovered {len(scan_targets)} pages')
                except Exception as _ce:
                    st.error(f'Crawl failed: {_ce}')
                    st.stop()

        if not scan_targets:
            st.warning('No pages found. Please check your URL or try another discovery method.')
            st.stop()


        # Add any manually entered extra pages
        for _ep_name, _ep_path in manual_pages:
            _p = _ep_path if _ep_path.startswith('/') else f'/{_ep_path}'
            if _p not in _seen:
                scan_targets.append((_ep_name, _make_url(_p)))
                _seen.add(_p)

        # Show discovered pages to user
        with st.expander(f'📋 {len(scan_targets)} pages discovered — click to preview', expanded=True):
            for _i, (_pn, _pu) in enumerate(scan_targets):
                _clean_disp = _pu.replace(f'{_scheme}://{_auth_pfx}', f'{_scheme}://') if _auth_pfx else _pu
                st.caption(f'{_i+1}. **{_pn}** — `{_clean_disp}`')

            if not scan_targets:
                st.error('Could not build scan targets. Check your base URL.')
                st.stop()
            st.caption(f'Will scan {len(scan_targets)} page(s): ' + ', '.join(f"{n} ({u.split(netloc_clean if "netloc_clean" in dir() else "@")[-1].split("@")[-1]})" for n,u in scan_targets[:5]) + ('...' if len(scan_targets)>5 else ''))
            progress_bar = st.progress(0, text=f'Scanning 0 / {len(scan_targets)} pages...')
            scan_summary = []

            for i, (pname, full_url) in enumerate(scan_targets):
                progress_bar.progress((i) / len(scan_targets), text=f'Scanning {i+1} / {len(scan_targets)}: {pname}...')
                scanned = quick_scan(full_url, page_name=pname)
                count = 0
                for r in scanned:
                    r['Page'] = pname          # override with correct page name
                    r['Event ID'] = f'ga{ga}'
                    ga += 1
                    count += 1
                all_rows.extend(scanned)
                scan_summary.append((pname, count))

            progress_bar.progress(1.0, text=f'Scan complete — {len(scan_targets)} pages scanned.')

            total_scanned = sum(c for _, c in scan_summary)
            with st.expander(f'Scan Summary — {total_scanned} elements detected across {len(scan_targets)} pages', expanded=True):
                for pname, count in scan_summary:
                    icon = '✅' if count > 0 else '⚠️'
                    st.caption(f'{icon} {pname}: {count} events')

        if all_rows:
            st.session_state.sdr_df = pd.DataFrame(all_rows)
            st.session_state.ga_counter = ga
            st.success(f'Draft ready — {len(all_rows)} total events across {len(scan_targets)} page(s)')
            st.rerun()
        else:
            st.warning('Please enter a Base URL to scan.')

if has_draft:
    with st.expander('Step 2 - Review and Edit Draft SDR', expanded=True):
        st.caption('Edit any cell directly. Use the + row button at the bottom to add events. Save before exporting.')
        COLS = ['Page','Category','Event Name','Action','Label','CTA Location','CTA Text','Business Intent','Page URL','Event ID']
        df_edit = st.session_state.sdr_df.copy()
        for c in COLS:
            if c not in df_edit.columns: df_edit[c] = ''
        edited = st.data_editor(
            df_edit[COLS], use_container_width=True, num_rows='dynamic', height=520,
            column_config={
                'Category': st.column_config.SelectboxColumn('Category', options=['navigation','exit','download','form','video','scroll','cta_clicks','header','footer','inpage','engagement'], required=True),
                'Action':   st.column_config.SelectboxColumn('Action',   options=['click','scroll','submit','play','impression','view'], required=False),
                'Business Intent': st.column_config.SelectboxColumn('Business Intent', options=['engagement','conversion','acquisition','consideration','awareness','support','exit','retention'], required=False),
                'CTA Location':    st.column_config.SelectboxColumn('CTA Location',    options=['header','footer','inpage','hero','sidebar','modal','banner'], required=False),
            }, key='sdr_editor'
        )
        if st.button('Save Changes', type='secondary'):
            st.session_state.sdr_df = edited.reset_index(drop=True)
            st.success(f'Saved - {len(edited)} events')
            st.rerun()

    with st.expander('Step 3 - Export SDR Excel', expanded=True):
        df_exp = st.session_state.sdr_df
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric('Total Events',  len(df_exp))
        c2.metric('Navigation',    len(df_exp[df_exp['Category'].isin(['navigation','header','footer','inpage','cta_clicks'])]))
        c3.metric('Forms',         len(df_exp[df_exp['Category']=='form']))
        c4.metric('Downloads',     len(df_exp[df_exp['Category']=='download']))
        c5.metric('Videos',        len(df_exp[df_exp['Category']=='video']))
        proj  = st.session_state.project_name or 'SDR'
        fname = f'{slug(proj)}_sdr.xlsx'
        buf   = build_excel(df_exp, proj)
        st.download_button(
            label='Download SDR Excel (6 sheets)',
            data=buf, file_name=fname,
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            type='primary', use_container_width=True
        )
        st.caption('Sheets: SDR Master | Link_Click | Exit_Click | Downloads | Forms | Videos')