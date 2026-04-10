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

def quick_scan(url):
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
            rows.append({"Page":"Scanned","Category":"download","Event Name":f"download_click_{slug(text)[:30]}","Action":"click","Label":full,"CTA Location":loc,"CTA Text":text,"Business Intent":"consideration","Page URL":url,"Event ID":""})
        elif fp.netloc and fp.netloc != parsed.netloc:
            rows.append({"Page":"Scanned","Category":"exit","Event Name":f"exit_click_{slug(text)[:30]}","Action":"click","Label":full,"CTA Location":loc,"CTA Text":text,"Business Intent":"exit","Page URL":url,"Event ID":""})
        elif href and not href.startswith('#') and not href.startswith('mailto'):
            rows.append({"Page":"Scanned","Category":"navigation","Event Name":f"link_click_{slug(text)[:30]}","Action":"click","Label":full,"CTA Location":loc,"CTA Text":text,"Business Intent":"engagement","Page URL":url,"Event ID":""})
    for frm in soup.find_all('form'):
        fname = frm.get('id') or frm.get('name') or 'contact_form'
        if isinstance(fname,list): fname='_'.join(fname)
        loc = detect_location(frm)
        for ev,intent in [('form_begins','acquisition'),('form_success','conversion'),('form_error','engagement'),('form_abandoned','engagement')]:
            rows.append({"Page":"Scanned","Category":"form","Event Name":f"{ev}_{slug(str(fname))[:20]}","Action":ev,"Label":str(fname),"CTA Location":loc,"CTA Text":str(fname),"Business Intent":intent,"Page URL":url,"Event ID":""})
    for v in soup.find_all(['video','iframe']):
        src = v.get('src','') or v.get('data-src','')
        if 'vimeo' in src or 'youtube' in src or v.name=='video':
            vname = v.get('title','') or 'video'
            loc = detect_location(v)
            for ev in ['video_begins','video_progression_25','video_progression_50','video_progression_75','video_ends']:
                rows.append({"Page":"Scanned","Category":"video","Event Name":ev,"Action":ev.split("_")[0],"Label":vname,"CTA Location":loc,"CTA Text":src,"Business Intent":"consideration","Page URL":url,"Event ID":""})
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
    pages_input = st.text_area('Pages', height=180, placeholder='Homepage | /\nHCP Page | /hcp\nISI | /isi\nResources | /resources')

    st.markdown('**Or scan a live / staging URL** (auto-imports detected events)')
    scan_url_input = st.text_input('Scan URL (optional)', placeholder='https://staging.example.com')

    if st.button('Generate Draft SDR', type='primary', use_container_width=True):
        all_rows = []
        ga = st.session_state.ga_counter
        pages = []
        if pages_input.strip():
            for line in pages_input.strip().splitlines():
                line = line.strip()
                if not line: continue
                if '|' in line:
                    parts = line.split('|', 1)
                    pages.append((parts[0].strip(), parts[1].strip()))
                else:
                    pages.append((line, f'/{slug(line)}'))
        for pname, purl in pages:
            new_rows, ga = infer_events(pname, purl, site_type, ga)
            all_rows.extend(new_rows)
        if scan_url_input.strip():
            with st.spinner('Scanning...'):
                scanned = quick_scan(scan_url_input.strip())
            for r in scanned:
                r['Event ID'] = f'ga{ga}'; ga += 1
            all_rows.extend(scanned)
            st.success(f'Scanned: {len(scanned)} elements detected')
        if all_rows:
            st.session_state.sdr_df = pd.DataFrame(all_rows)
            st.session_state.ga_counter = ga
            st.success(f'Draft ready: {len(all_rows)} events across {len(pages)} pages')
            st.rerun()
        else:
            st.warning('Add at least one page or a scan URL.')

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