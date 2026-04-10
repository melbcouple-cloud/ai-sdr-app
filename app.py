import hmac
import streamlit as st
import pandas as pd
import os
import re
from io import BytesIO
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

#  PASSWORD 
def check_password():
    def password_entered():
        try:
            correct = st.secrets.get("APP_PASSWORD", "")
        except Exception:
            correct = os.environ.get("APP_PASSWORD", "")
        if correct and hmac.compare_digest(st.session_state["password"], correct):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False
    if st.session_state.get("password_correct", False):
        return True
    st.markdown("## SDR Generator - Login")
    st.text_input("Password", type="password", on_change=password_entered, key="password")
    if st.session_state.get("password_correct") == False:
        st.error("Incorrect password.")
    return False

_pw_required = False
try:
    _pw_required = bool(st.secrets.get("APP_PASSWORD", ""))
except Exception:
    _pw_required = bool(os.environ.get("APP_PASSWORD", ""))
if _pw_required and not check_password():
    st.stop()

#  SESSION STATE 
for k, v in {
    "project_name": "", "base_url": "", "pages": [],
    "link_clicks": [], "exit_clicks": [], "downloads": [],
    "forms": [], "videos": [], "ga_counter": 4
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

def next_ga():
    cid = st.session_state.ga_counter
    st.session_state.ga_counter += 1
    return cid

def slug(t):
    return re.sub(r"[^a-z0-9]+", "_", t.lower().strip()).strip("_")

def page_map():
    return {p["name"]: p["url"] for p in st.session_state.pages}

LOCATIONS  = ["header", "footer", "inpage", "hero", "sidebar", "modal", "banner"]
CTA_TYPES  = ["link", "button", "logo", "image", "tab", "accordion", "card"]
FILE_TYPES = ["pdf", "jpg", "png", "mp4", "docx", "xlsx", "zip"]
FORM_FIELDS= ["first_name", "last_name", "email", "zip", "phone",
              "organization", "speciality", "dob", "npi", "message"]
VID_SRC    = ["html5", "vimeo", "youtube", "brightcove"]

#  SCANNER 
def scan_url(url):
    """Scan a URL and return detected elements grouped by type."""
    from urllib.parse import urlparse, urljoin
    results = {"links": [], "exits": [], "downloads": [], "forms": [], "videos": []}
    parsed  = urlparse(url)
    base    = f"{parsed.scheme}://{parsed.netloc}"
    raw_html = None

    # Strategy 1: curl_cffi
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, impersonate="chrome110", timeout=20,
                     headers={"Accept-Language": "en-US,en;q=0.9"})
        if r.status_code == 200:
            raw_html = r.text
    except Exception:
        pass

    # Strategy 2: requests fallback
    if not raw_html:
        try:
            import requests
            r = requests.get(url, timeout=15,
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"})
            if r.status_code == 200:
                raw_html = r.text
        except Exception:
            pass

    if not raw_html:
        return results, "Could not fetch page. Check URL or credentials."

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw_html, "lxml")
    dl_exts = {".pdf",".docx",".xlsx",".zip",".ppt",".pptx",".mp4",".jpg",".png"}

    for a in soup.find_all("a", href=True):
        href = a.get("href","").strip()
        text = a.get_text(strip=True) or href
        full = urljoin(url, href)
        fp   = urlparse(full)
        ext  = os.path.splitext(fp.path)[1].lower()

        if ext in dl_exts:
            results["downloads"].append({"file_text": text, "file_type": ext.lstrip("."),
                                          "file_url": full, "file_location": "inpage",
                                          "current_page_url": url})
        elif fp.netloc and fp.netloc != parsed.netloc:
            results["exits"].append({"exit_linkname": text, "exit_url": full,
                                      "exit_location": "inpage", "current_page_url": url})
        elif href and not href.startswith("#") and not href.startswith("mailto"):
            results["links"].append({"cta_text": text, "cta_link": full,
                                      "cta_location": "inpage", "cta_type": "link",
                                      "current_page_url": url})

    for form in soup.find_all("form"):
        fname = (form.get("id") or form.get("name") or
                 form.get("class","form") or "contact_form")
        if isinstance(fname, list):
            fname = "_".join(fname)
        fields = [i.get("name","") for i in form.find_all(["input","select","textarea"])
                  if i.get("name") and i.get("type","text") not in ("hidden","submit","button")]
        results["forms"].append({"form_name": str(fname), "fields": " | ".join(fields[:8]),
                                  "current_page_url": url})

    for v in soup.find_all(["video","iframe"]):
        src = v.get("src","") or v.get("data-src","")
        if "vimeo" in src or "youtube" in src or v.tag == "video":
            vname = v.get("title","") or v.get("alt","") or "video"
            vsrc  = "vimeo" if "vimeo" in src else ("youtube" if "youtube" in src else "html5")
            results["videos"].append({"video_name": vname, "video_link": src,
                                       "video_source": vsrc, "duration_secs": 120,
                                       "current_page_url": url})

    msg = (f"Found {len(results['links'])} links, {len(results['exits'])} exits, "
           f"{len(results['downloads'])} downloads, {len(results['forms'])} forms, "
           f"{len(results['videos'])} videos")
    return results, msg

#  EXCEL BUILDER 
def build_excel():
    wb  = openpyxl.Workbook()
    hf  = PatternFill("solid", fgColor="1F4E79")
    hfont = Font(color="FFFFFF", bold=True, size=10)
    af  = PatternFill("solid", fgColor="EBF3FB")
    thin = Side(style="thin", color="BFBFBF")
    bdr  = Border(left=thin, right=thin, top=thin, bottom=thin)
    ctr  = Alignment(horizontal="center", vertical="center", wrap_text=True)
    lft  = Alignment(horizontal="left",   vertical="center", wrap_text=True)

    def hdr(ws, cols, widths):
        ws.row_dimensions[1].height = 26
        for ci, (c, w) in enumerate(zip(cols, widths), 1):
            cell = ws.cell(row=1, column=ci, value=c)
            cell.fill = hf; cell.font = hfont
            cell.alignment = ctr; cell.border = bdr
            ws.column_dimensions[get_column_letter(ci)].width = w

    def row(ws, vals, ri):
        fill = af if ri % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
        for ci, v in enumerate(vals, 1):
            cell = ws.cell(row=ri, column=ci, value=v)
            cell.fill = fill; cell.font = Font(size=9)
            cell.alignment = lft; cell.border = bdr

    # Sheet 1 - SDR Master
    ws1 = wb.active; ws1.title = "SDR"
    hdr(ws1, ["No","Category","Event Name","Action","Label","Notes"],
             [6,18,34,18,45,30])
    master = [
        ("","video","video_impression","Video name","impression",""),
        ("","video","video_play","Video name","start",""),
        ("","video","video_percent","Video name","25% | 50% | 75% | 100%",""),
        ("","video","video_keymessage_complete","Video name","Complete",""),
        ("","header","navigation","<click_text>","Click URL",""),
        ("","footer","navigation","<click_text>","Click URL",""),
        ("","inpage","cta_clicks","page url","<click_text>",""),
        ("","download","downloads","click url","<click_text>",""),
        ("","scroll","scroll_depth_signpost","page url","content name / signpost",""),
        ("","scroll","scroll_percentage","page url","25% | 50% | 75% | 100%",""),
        ("","Visits","Overall_Engaged_Visit","Engagement","2 mins+ or form start or video play",""),
        ("","Visits","Overall_Deep_Engaged_Visit","Deep Engagement","Download or registration or video complete or 4+ pages",""),
        ("","time_on_site","Time_On_Site","seconds (30,60,90,120+)","Page Name",""),
        ("","form","form_impression","form name","impression",""),
        ("","form","form_start","form name","start",""),
        ("","form","form_field_complete","form name","first_name | email | zip | speciality",""),
        ("","form","form_field_complete_submitted","form name","first_name | email | zip | speciality",""),
        ("","form","form_validation_errors","form name","Fields required",""),
        ("","form","form_abandon","form name","first_name | email | zip | speciality",""),
    ]
    for ri, r_ in enumerate(master, 2):
        row(ws1, r_, ri)

    # Sheet 2 - Link_Click
    ws2 = wb.create_sheet("Link_Click")
    hdr(ws2, ["URL","event","event_name","cta_link","cta_location","cta_text","cta_type","current_page_url","screenshots"],
             [35,22,22,40,15,28,12,40,15])
    for ri, lc in enumerate(st.session_state.link_clicks, 2):
        row(ws2, [lc.get("page_url",""), lc.get("event",""), "link_click",
                  lc.get("cta_link",""), lc.get("cta_location",""),
                  lc.get("cta_text",""), lc.get("cta_type","link"),
                  lc.get("current_page_url",""), ""], ri)

    # Sheet 3 - Exit_Click
    ws3 = wb.create_sheet("Exit_Click")
    hdr(ws3, ["URL","event","event_name","exit_linkname","exit_url","exit_location","current_page_url","screenshots"],
             [35,22,22,30,42,15,40,15])
    for ri, ec in enumerate(st.session_state.exit_clicks, 2):
        row(ws3, [ec.get("page_url",""), ec.get("event",""), "exit_click",
                  ec.get("exit_linkname",""), ec.get("exit_url",""),
                  ec.get("exit_location",""), ec.get("current_page_url",""), ""], ri)

    # Sheet 4 - Downloads
    ws4 = wb.create_sheet("Downloads")
    hdr(ws4, ["URL","event","event_name","file_text","file_type","file_url","file_location","current_page_url","screenshots"],
             [35,22,22,30,10,42,15,40,15])
    for ri, dl in enumerate(st.session_state.downloads, 2):
        row(ws4, [dl.get("page_url",""), dl.get("event",""), "download_click",
                  dl.get("file_text",""), dl.get("file_type","pdf"),
                  dl.get("file_url",""), dl.get("file_location","inpage"),
                  dl.get("current_page_url",""), ""], ri)

    # Sheet 5 - Forms
    ws5 = wb.create_sheet("Forms")
    hdr(ws5, ["URL","GA4 Event (event)","GA4 Event (event_name)","form_title","form_info","current_page_url"],
             [35,25,25,30,48,40])
    ri5 = 2
    for frm in st.session_state.forms:
        gid = frm.get("ga_id", 4)
        fname = frm.get("form_name","")
        fields = frm.get("fields","")
        purl = frm.get("current_page_url", frm.get("page_url",""))
        for ev, en, fi in [
            (f"form_begins_ga{gid}",    "form_begins",    "<< first field entry >>"),
            (f"form_success_ga{gid+1}", "form_success",   "<< dynamic value >>"),
            (f"form_error_ga{gid+2}",   "form_error",     "recaptcha validation failed"),
            (f"form_abandoned_ga{gid+3}","form_abandoned", f"<< step no >> | {fields}"),
        ]:
            row(ws5, [purl, ev, en, fname, fi, purl], ri5); ri5 += 1

    # Sheet 6 - Videos
    ws6 = wb.create_sheet("Videos")
    hdr(ws6, ["URL","GA4_event","Video_name","Video_elapsed_time","Video_link","Video_source","current_page_url"],
             [35,28,30,20,42,12,40])
    ri6 = 2
    for vid in st.session_state.videos:
        dur  = vid.get("duration_secs", 120)
        purl = vid.get("current_page_url", vid.get("page_url",""))
        for ev, el in [
            ("video_begins", 1), ("video_paused","<<current time>>"),
            ("video_paused_30s", 30), ("video_paused_60s", 60),
            ("video_progression_25%", int(dur*0.25)),
            ("video_progression_50%", int(dur*0.50)),
            ("video_progression_75%", int(dur*0.75)),
            ("video_ends", dur),
        ]:
            row(ws6, [purl, ev, vid.get("video_name",""), el,
                      vid.get("video_link",""), vid.get("video_source","html5"), purl], ri6)
            ri6 += 1

    buf = BytesIO(); wb.save(buf); buf.seek(0)
    return buf

#  PAGE CONFIG 
st.set_page_config(page_title="SDR Generator v2", layout="wide")

#  SIDEBAR 
with st.sidebar:
    st.markdown("### SDR Generator v2")
    st.caption("Pre-Build Planner + Post-Build Scanner")
    st.divider()
    st.session_state.project_name = st.text_input(
        "Project Name", value=st.session_state.project_name,
        placeholder="e.g. Viewuvealdifferently")
    st.session_state.base_url = st.text_input(
        "Base URL", value=st.session_state.base_url,
        placeholder="https://www.example.com")
    st.divider()
    st.caption("Event counter")
    st.code(f"Next GA ID: ga{st.session_state.ga_counter}")
    if st.button("Reset to ga4"):
        st.session_state.ga_counter = 4; st.rerun()
    st.divider()
    counts = {
        "Link Clicks":  len(st.session_state.link_clicks),
        "Exit Clicks":  len(st.session_state.exit_clicks),
        "Downloads":    len(st.session_state.downloads),
        "Forms":        len(st.session_state.forms),
        "Videos":       len(st.session_state.videos),
    }
    for k, v in counts.items():
        st.metric(k, v)

#  HEADER 
st.title("SDR Generator v2")
st.caption("Step 1: Define pages and map CTAs (Pre-Build). Step 2: Scan staging site to validate (Post-Build). Step 3: Export 6-sheet Excel.")

#  TABS 
t1,t2,t3,t4,t5,t6,t7,t8 = st.tabs([
    "Project Setup","Link Clicks","Exit Clicks",
    "Downloads","Forms","Videos","Scanner","Export"
])

page_names_list = [p["name"] for p in st.session_state.pages] or ["(Add pages first)"]

#  TAB 1: Project Setup 
with t1:
    st.header("Site Pages")
    st.caption("Define every page in the site architecture. These become the source for all CTA mapping.")
    with st.form("pg_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        pg_name = c1.text_input("Page Name", placeholder="e.g. Homepage")
        pg_url  = c2.text_input("Page URL",  placeholder="https://www.example.com/")
        if st.form_submit_button("Add Page") and pg_name:
            st.session_state.pages.append({"name": pg_name, "url": pg_url or "/"})
            st.rerun()

    if st.session_state.pages:
        for i, pg in enumerate(st.session_state.pages):
            c1,c2,c3 = st.columns([3,5,1])
            c1.write(f"**{pg['name']}**"); c2.write(pg["url"])
            if c3.button("X", key=f"rmpg{i}"):
                st.session_state.pages.pop(i); st.rerun()
    else:
        st.info("No pages yet. Add your site pages above.")

#  TAB 2: Link Clicks 
with t2:
    st.header("Link Clicks")
    st.caption("Internal navigation - header nav, footer links, in-page CTAs")
    with st.form("lc_form", clear_on_submit=True):
        c1,c2 = st.columns(2)
        lc_pg  = c1.selectbox("Page", page_names_list, key="lc_pg")
        lc_loc = c2.selectbox("Location", LOCATIONS, key="lc_loc")
        c3,c4  = st.columns(2)
        lc_txt = c3.text_input("CTA Text",  placeholder="e.g. About UM")
        lc_typ = c4.selectbox("CTA Type", CTA_TYPES, key="lc_typ")
        lc_url = st.text_input("Destination URL", placeholder="https://www.example.com/about-um")
        if st.form_submit_button("Add Link Click") and lc_txt:
            gid  = next_ga()
            purl = page_map().get(lc_pg, "/")
            st.session_state.link_clicks.append({
                "page_url": purl, "event": f"link_click_ga{gid}",
                "cta_link": lc_url, "cta_location": lc_loc, "cta_text": lc_txt,
                "cta_type": lc_typ, "current_page_url": purl, "page_label": lc_pg,
                "source": "manual"
            })
            st.rerun()

    if st.session_state.link_clicks:
        df = pd.DataFrame(st.session_state.link_clicks)
        show_cols = [c for c in ["page_label","event","cta_location","cta_text","cta_type","cta_link","source"] if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True, height=300)
        if st.button("Clear All", key="clrlc"):
            st.session_state.link_clicks = []; st.rerun()
    else:
        st.info("No link clicks yet. Add above or import from Scanner tab.")

#  TAB 3: Exit Clicks 
with t3:
    st.header("Exit Clicks")
    st.caption("Links that take users off the website to external domains")
    with st.form("ec_form", clear_on_submit=True):
        c1,c2  = st.columns(2)
        ec_pg  = c1.selectbox("Page", page_names_list, key="ec_pg")
        ec_loc = c2.selectbox("Location", LOCATIONS, key="ec_loc")
        c3,c4  = st.columns(2)
        ec_lnm = c3.text_input("Link / Button Text", placeholder="e.g. Contact Us")
        ec_url = c4.text_input("Exit URL", placeholder="https://www.ideayabio.com/contact/")
        if st.form_submit_button("Add Exit Click") and ec_lnm:
            gid  = next_ga()
            purl = page_map().get(ec_pg, "/")
            st.session_state.exit_clicks.append({
                "page_url": purl, "event": f"exit_click_ga{gid}",
                "exit_linkname": ec_lnm, "exit_url": ec_url,
                "exit_location": ec_loc, "current_page_url": purl,
                "page_label": ec_pg, "source": "manual"
            })
            st.rerun()

    if st.session_state.exit_clicks:
        df = pd.DataFrame(st.session_state.exit_clicks)
        show_cols = [c for c in ["page_label","event","exit_location","exit_linkname","exit_url","source"] if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True, height=300)
        if st.button("Clear All", key="clrec"):
            st.session_state.exit_clicks = []; st.rerun()
    else:
        st.info("No exit clicks yet.")

#  TAB 4: Downloads 
with t4:
    st.header("Downloads")
    st.caption("PDFs, images, documents, and file downloads")
    with st.form("dl_form", clear_on_submit=True):
        c1,c2  = st.columns(2)
        dl_pg  = c1.selectbox("Page", page_names_list, key="dl_pg")
        dl_loc = c2.selectbox("Location", LOCATIONS, key="dl_loc")
        c3,c4  = st.columns(2)
        dl_txt = c3.text_input("Link / Button Text", placeholder="e.g. Download Prescribing Info")
        dl_typ = c4.selectbox("File Type", FILE_TYPES, key="dl_typ")
        dl_url = st.text_input("File URL", placeholder="https://www.example.com/files/pi.pdf")
        if st.form_submit_button("Add Download") and dl_txt:
            gid  = next_ga()
            purl = page_map().get(dl_pg, "/")
            st.session_state.downloads.append({
                "page_url": purl, "event": f"download_click_ga{gid}",
                "file_text": dl_txt, "file_type": dl_typ, "file_url": dl_url,
                "file_location": dl_loc, "current_page_url": purl,
                "page_label": dl_pg, "source": "manual"
            })
            st.rerun()

    if st.session_state.downloads:
        df = pd.DataFrame(st.session_state.downloads)
        show_cols = [c for c in ["page_label","event","file_location","file_text","file_type","file_url","source"] if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True, height=300)
        if st.button("Clear All", key="clrdl"):
            st.session_state.downloads = []; st.rerun()
    else:
        st.info("No downloads yet.")

#  TAB 5: Forms 
with t5:
    st.header("Forms")
    st.caption("Each form generates 4 events: begins, success, error, abandoned")
    with st.form("fm_form", clear_on_submit=True):
        c1,c2  = st.columns(2)
        fm_pg  = c1.selectbox("Page", page_names_list, key="fm_pg")
        fm_nm  = c2.text_input("Form Name", placeholder="e.g. HCP Registration Form")
        fm_fld = st.multiselect("Form Fields", FORM_FIELDS,
                                default=["first_name","last_name","email"])
        if st.form_submit_button("Add Form") and fm_nm:
            gid  = next_ga()
            purl = page_map().get(fm_pg, "/")
            st.session_state.forms.append({
                "page_url": purl, "form_name": fm_nm,
                "fields": " | ".join(fm_fld), "ga_id": gid,
                "current_page_url": purl, "page_label": fm_pg, "source": "manual"
            })
            st.session_state.ga_counter += 3
            st.rerun()

    if st.session_state.forms:
        df = pd.DataFrame(st.session_state.forms)
        show_cols = [c for c in ["page_label","form_name","fields","ga_id","source"] if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True, height=300)
        if st.button("Clear All", key="clrfm"):
            st.session_state.forms = []; st.rerun()
    else:
        st.info("No forms yet.")

#  TAB 6: Videos 
with t6:
    st.header("Videos")
    st.caption("Each video generates 8 milestone events: begins, paused, 30s, 60s, 25%, 50%, 75%, ends")
    with st.form("vd_form", clear_on_submit=True):
        c1,c2  = st.columns(2)
        vd_pg  = c1.selectbox("Page", page_names_list, key="vd_pg")
        vd_nm  = c2.text_input("Video Name", placeholder="e.g. MOA Animation")
        c3,c4  = st.columns(2)
        vd_lnk = c3.text_input("Video URL", placeholder="https://player.vimeo.com/video/...")
        vd_src = c4.selectbox("Source", VID_SRC, key="vd_src")
        vd_dur = st.number_input("Duration (seconds)", min_value=10, value=120, step=10)
        if st.form_submit_button("Add Video") and vd_nm:
            purl = page_map().get(vd_pg, "/")
            st.session_state.videos.append({
                "page_url": purl, "video_name": vd_nm, "video_link": vd_lnk,
                "video_source": vd_src, "duration_secs": int(vd_dur),
                "current_page_url": purl, "page_label": vd_pg, "source": "manual"
            })
            st.rerun()

    if st.session_state.videos:
        df = pd.DataFrame(st.session_state.videos)
        show_cols = [c for c in ["page_label","video_name","video_source","duration_secs","source"] if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True, height=300)
        if st.button("Clear All", key="clrvd"):
            st.session_state.videos = []; st.rerun()
    else:
        st.info("No videos yet.")

#  TAB 7: Scanner 
with t7:
    st.header("Post-Build Scanner")
    st.caption("Scan your staging or live site to auto-detect elements. Results merge with your manually defined plan.")

    sc_url = st.text_input("URL to Scan",
        placeholder="https://user:pass@stage.example.com/ or https://www.example.com/")
    st.caption("For password-protected staging sites use: https://username:password@staging.example.com/")

    if st.button("Scan URL", type="primary") and sc_url:
        with st.spinner("Scanning..."):
            results, msg = scan_url(sc_url)
        st.success(msg)

        if results["links"] or results["exits"] or results["downloads"] or results["forms"] or results["videos"]:
            st.subheader("Scan Results Preview")

            if results["links"]:
                st.markdown(f"**Internal Links ({len(results['links'])})**")
                st.dataframe(pd.DataFrame(results["links"]), use_container_width=True, height=200)

            if results["exits"]:
                st.markdown(f"**Exit Links ({len(results['exits'])})**")
                st.dataframe(pd.DataFrame(results["exits"]), use_container_width=True, height=200)

            if results["downloads"]:
                st.markdown(f"**Downloads ({len(results['downloads'])})**")
                st.dataframe(pd.DataFrame(results["downloads"]), use_container_width=True, height=200)

            if results["forms"]:
                st.markdown(f"**Forms ({len(results['forms'])})**")
                st.dataframe(pd.DataFrame(results["forms"]), use_container_width=True, height=200)

            if results["videos"]:
                st.markdown(f"**Videos ({len(results['videos'])})**")
                st.dataframe(pd.DataFrame(results["videos"]), use_container_width=True, height=200)

            st.divider()
            st.subheader("Import to Plan")
            st.caption("Select what to import. Duplicates (same text + URL) are skipped automatically.")

            imp_links = st.checkbox(f"Import {len(results['links'])} link clicks", value=True)
            imp_exits = st.checkbox(f"Import {len(results['exits'])} exit clicks", value=True)
            imp_dls   = st.checkbox(f"Import {len(results['downloads'])} downloads", value=True)
            imp_forms = st.checkbox(f"Import {len(results['forms'])} forms", value=True)
            imp_vids  = st.checkbox(f"Import {len(results['videos'])} videos", value=True)

            if st.button("Import Selected to Plan", type="primary"):
                imported = 0
                purl = sc_url

                if imp_links:
                    existing = {(x["cta_text"], x.get("cta_link","")) for x in st.session_state.link_clicks}
                    for lc in results["links"]:
                        if (lc["cta_text"], lc["cta_link"]) not in existing:
                            gid = next_ga()
                            st.session_state.link_clicks.append({
                                **lc, "event": f"link_click_ga{gid}",
                                "page_url": purl, "page_label": "Scanned",
                                "source": "scanner"
                            })
                            imported += 1

                if imp_exits:
                    existing = {(x["exit_linkname"], x.get("exit_url","")) for x in st.session_state.exit_clicks}
                    for ec in results["exits"]:
                        if (ec["exit_linkname"], ec["exit_url"]) not in existing:
                            gid = next_ga()
                            st.session_state.exit_clicks.append({
                                **ec, "event": f"exit_click_ga{gid}",
                                "page_url": purl, "page_label": "Scanned",
                                "source": "scanner"
                            })
                            imported += 1

                if imp_dls:
                    existing = {x["file_text"] for x in st.session_state.downloads}
                    for dl in results["downloads"]:
                        if dl["file_text"] not in existing:
                            gid = next_ga()
                            st.session_state.downloads.append({
                                **dl, "event": f"download_click_ga{gid}",
                                "page_url": purl, "page_label": "Scanned",
                                "source": "scanner"
                            })
                            imported += 1

                if imp_forms:
                    existing = {x["form_name"] for x in st.session_state.forms}
                    for frm in results["forms"]:
                        if frm["form_name"] not in existing:
                            gid = next_ga()
                            st.session_state.forms.append({
                                **frm, "ga_id": gid,
                                "page_url": purl, "page_label": "Scanned",
                                "source": "scanner"
                            })
                            st.session_state.ga_counter += 3
                            imported += 1

                if imp_vids:
                    existing = {x["video_name"] for x in st.session_state.videos}
                    for vid in results["videos"]:
                        if vid["video_name"] not in existing:
                            st.session_state.videos.append({
                                **vid, "page_url": purl,
                                "page_label": "Scanned", "source": "scanner"
                            })
                            imported += 1

                st.success(f"Imported {imported} items into the plan. Check the tabs above.")
                st.rerun()
        else:
            st.warning("No trackable elements found. The site may require a real browser or is blocking automated access.")

#  TAB 8: Export 
with t8:
    st.header("Export SDR Excel")

    total = (len(st.session_state.link_clicks) +
             len(st.session_state.exit_clicks) +
             len(st.session_state.downloads) +
             len(st.session_state.forms) * 4 +
             len(st.session_state.videos) * 8)

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("Link Clicks",  len(st.session_state.link_clicks))
    c2.metric("Exit Clicks",  len(st.session_state.exit_clicks))
    c3.metric("Downloads",    len(st.session_state.downloads))
    c4.metric("Forms",        len(st.session_state.forms))
    c5.metric("Videos",       len(st.session_state.videos))
    c6.metric("Total Events", total)

    st.divider()

    if total == 0:
        st.warning("No events in plan yet. Use the tabs above to add link clicks, exit clicks, downloads, forms, and videos.")
    else:
        proj     = st.session_state.project_name or "SDR"
        filename = f"{slug(proj)}_sdr.xlsx"
        buf      = build_excel()
        st.download_button(
            label="Download SDR Excel (6 sheets)",
            data=buf, file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary", use_container_width=True
        )
        st.caption("Sheets: SDR Master | Link_Click | Exit_Click | Downloads | Forms | Videos")
        st.divider()
        st.subheader("Full Plan Summary")
        for label, items, cols in [
            ("Link Clicks", st.session_state.link_clicks,
             ["page_label","event","cta_location","cta_text","cta_type","source"]),
            ("Exit Clicks", st.session_state.exit_clicks,
             ["page_label","event","exit_location","exit_linkname","exit_url","source"]),
            ("Downloads",   st.session_state.downloads,
             ["page_label","event","file_location","file_text","file_type","source"]),
            ("Forms",       st.session_state.forms,
             ["page_label","form_name","fields","source"]),
            ("Videos",      st.session_state.videos,
             ["page_label","video_name","video_source","duration_secs","source"]),
        ]:
            if items:
                st.markdown(f"**{label} ({len(items)})**")
                df = pd.DataFrame(items)
                show = [c for c in cols if c in df.columns]
                st.dataframe(df[show], use_container_width=True, height=200)
