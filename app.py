import hmac
import streamlit as st

def check_password():
    def password_entered():
        if hmac.compare_digest(st.session_state["password"], st.secrets["APP_PASSWORD"]):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.markdown("## ?? SDR Generator � Login")
    st.text_input("Password", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state:
        st.error("? Incorrect password")
    return False

if not check_password():
    st.stop()  # Everything below this line is protected
import streamlit as st
import pandas as pd
from scanner import scan_website, scan_multiple_urls
from classifier import classify_elements, enrich_with_llm, generate_isi_events, get_pharma_template, list_pharma_templates
from exporter import to_csv, to_ga4_json, to_gtm_datalayer

st.set_page_config(page_title="AI-Assisted SDR Generator", page_icon="📊", layout="wide")

CATEGORY_OPTIONS = [
    "navigation", "exit", "download", "conversion",
    "form_interaction", "ui_interaction", "engagement", "other"
]
INTENT_OPTIONS = [
    "conversion", "acquisition", "consideration", "awareness",
    "retention", "engagement", "lead_nurture", "support", "discovery", "exit"
]

# ── SIDEBAR ──────────────────────────────────────────────────
with st.sidebar:
    st.title("📊 SDR Generator")
    st.caption("AI-Assisted Analytics Tracking Plan")
    st.divider()

    st.markdown("### 🎯 What to Track")
    options = {
        "track_links":     st.checkbox("Internal Link Clicks",   value=True),
        "track_exit":      st.checkbox("External / Exit Clicks", value=True),
        "track_downloads": st.checkbox("File Downloads",         value=True),
        "track_forms":     st.checkbox("Forms & Form Fields",    value=True),
        "track_videos":    st.checkbox("Videos",                 value=True),
        "track_buttons":   st.checkbox("Buttons / CTAs",         value=True),
    }
    st.divider()

    st.markdown("### 🔑 Anti-Bot API Key")
    st.caption("Required for Incapsula / Cloudflare protected pharma sites")
    scraper_key = st.text_input(
        "ScraperAPI Key",
        type="password",
        placeholder="Get free key at scraperapi.com",
    )
    options["scraper_api_key"] = scraper_key
    if scraper_key:
        st.success("✅ ScraperAPI key loaded")
    else:
        st.info("3 free strategies used automatically")
    st.divider()

    st.markdown("### 🤖 AI Enrichment (Optional)")
    llm_provider = st.selectbox("LLM Provider", ["None", "Groq (Free)", "OpenAI"])
    llm_api_key  = ""
    if llm_provider != "None":
        llm_api_key = st.text_input("API Key", type="password", placeholder="Paste your API key")

# ── HEADER ───────────────────────────────────────────────────
st.markdown("## 📊 AI-Assisted SDR Generator")
st.caption("Generate a GA4-ready tracking plan from any website — with AI assistance and manual override.")

tab_scan, tab_manual, tab_templates, tab_howto = st.tabs([
    "🔍 Auto Scan", "✏️ Manual Entry", "💊 Pharma Templates", "📖 How It Works"
])

# ── TAB 1: AUTO SCAN ─────────────────────────────────────────
with tab_scan:
    st.markdown("#### Enter URLs to Scan")
    st.caption("Enter one URL per line — homepage, HCP page, patient support page, etc.")

    url_input = st.text_area(
        "URLs",
        placeholder="https://www.example.com/\nhttps://www.example.com/page1/\nhttps://www.example.com/page2/",
        height=120,
        label_visibility="collapsed"
    )
    scan_clicked = st.button("🚀 Scan All URLs", type="primary", width='stretch')

    if scan_clicked and url_input.strip():
        urls = [u.strip() for u in url_input.strip().splitlines() if u.strip()]
        with st.status(f"Scanning {len(urls)} URL(s)...", expanded=True) as status:
            for i, u in enumerate(urls, 1):
                st.write(f"🌐 [{i}/{len(urls)}] Scanning: {u}")
            scan_result  = scan_multiple_urls(urls, options)
            raw_elements = scan_result["elements"]
            meta         = scan_result["meta"]
            strategy     = meta.get("strategy_used", "unknown")
            st.write(f"✅ Found **{len(raw_elements)}** raw elements across **{meta.get('pages_scanned',1)}** page(s) via **{strategy}**")
            st.write("🧠 Classifying + detecting ISI events...")
            rows = classify_elements(raw_elements, options)
            isi_rows = generate_isi_events(raw_elements)
            if isi_rows:
                rows = isi_rows + rows
                st.write(f"📋 Auto-added **{len(isi_rows)} ISI scroll events** (ISI section detected)")
            if llm_provider != "None" and llm_api_key:
                st.write("✨ Enriching with AI...")
                rows = enrich_with_llm(rows, llm_api_key, "groq" if "Groq" in llm_provider else "openai")
            st.session_state["sdr_rows"]  = rows
            st.session_state["scan_meta"] = meta
            for w in scan_result["warnings"]:
                st.warning(w)
            status.update(label=f"✅ Scan complete! {len(rows)} events generated.", state="complete")

    if st.session_state.get("sdr_rows"):
        rows = st.session_state["sdr_rows"]
        meta = st.session_state.get("scan_meta", {})
        df   = pd.DataFrame(rows)

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Total Events",      len(df))
        m2.metric("Pages Scanned",     meta.get("pages_scanned", 1))
        m3.metric("Forms Detected",    meta.get("forms_found", 0))
        m4.metric("Categories",        df["Category"].nunique())
        m5.metric("Conversion Events", len(df[df["Business Intent"] == "conversion"]))
        m6.metric("ISI Events",        len(df[df["Source"] == "auto_isi"]))
        st.divider()

        fc1, fc2, fc3 = st.columns(3)
        cats    = fc1.multiselect("Filter by Category",        sorted(df["Category"].unique()), key="fcat")
        intents = fc2.multiselect("Filter by Business Intent", sorted(df["Business Intent"].unique()), key="fint")
        sources = fc3.multiselect("Filter by Source",          sorted(df["Source"].unique()), key="fsrc")
        filtered = df.copy()
        if cats:    filtered = filtered[filtered["Category"].isin(cats)]
        if intents: filtered = filtered[filtered["Business Intent"].isin(intents)]
        if sources: filtered = filtered[filtered["Source"].isin(sources)]
        st.caption(f"Showing {len(filtered)} of {len(df)} events")

        edited = st.data_editor(
            filtered,
            column_config={
                "Category":        st.column_config.SelectboxColumn("Category",        options=CATEGORY_OPTIONS, required=True),
                "Business Intent": st.column_config.SelectboxColumn("Business Intent", options=INTENT_OPTIONS,   required=True),
                "Event Name":      st.column_config.TextColumn("Event Name (GA4)", max_chars=40),
                "Notes":           st.column_config.TextColumn("Notes", width="medium"),
            },
            hide_index=True, width='stretch', num_rows="dynamic", key="scan_editor",
        )
        st.session_state["sdr_rows"] = edited.to_dict("records")
        st.divider()

        final = st.session_state["sdr_rows"]
        e1, e2, e3 = st.columns(3)
        e1.download_button("📥 CSV",             to_csv(final),           "sdr_tracking_plan.csv", "text/csv",         width='stretch', key="s_csv")
        e2.download_button("📥 GA4 JSON",         to_ga4_json(final),      "ga4_events.json",       "application/json", width='stretch', key="s_json")
        e3.download_button("📥 GTM dataLayer JS", to_gtm_datalayer(final), "gtm_datalayer.js",      "text/javascript",  width='stretch', key="s_gtm")

    elif scan_clicked:
        st.info("No elements found. Add a ScraperAPI key or use Manual Entry + Templates tabs.")

# ── TAB 2: MANUAL ENTRY ──────────────────────────────────────
with tab_manual:
    st.markdown("### ✏️ Manual SDR Entry")
    st.caption("Add events the scanner cannot detect — React forms, HubSpot embeds, CTA popups, ISI clicks.")

    manual_df = pd.DataFrame(
        st.session_state.get("sdr_rows", []),
        columns=["Category", "Event Name", "Action", "Label", "Business Intent", "Element Type", "Source", "Notes"]
    )
    edited_manual = st.data_editor(
        manual_df,
        column_config={
            "Category":        st.column_config.SelectboxColumn("Category",        options=CATEGORY_OPTIONS, required=True),
            "Business Intent": st.column_config.SelectboxColumn("Business Intent", options=INTENT_OPTIONS,   required=True),
            "Event Name":      st.column_config.TextColumn("Event Name (GA4)", max_chars=40),
        },
        hide_index=True, width='stretch', num_rows="dynamic", key="manual_editor",
    )
    if st.button("💾 Save Manual Entries", type="primary", key="save_manual"):
        st.session_state["sdr_rows"] = edited_manual.dropna(how="all").to_dict("records")
        st.success(f"✅ Saved {len(st.session_state['sdr_rows'])} events.")

    if st.session_state.get("sdr_rows"):
        final = st.session_state["sdr_rows"]
        st.divider()
        d1, d2, d3 = st.columns(3)
        d1.download_button("📥 CSV",             to_csv(final),           "sdr_tracking_plan.csv", "text/csv",         width='stretch', key="m_csv")
        d2.download_button("📥 GA4 JSON",         to_ga4_json(final),      "ga4_events.json",       "application/json", width='stretch', key="m_json")
        d3.download_button("📥 GTM dataLayer JS", to_gtm_datalayer(final), "gtm_datalayer.js",      "text/javascript",  width='stretch', key="m_gtm")

# ── TAB 3: PHARMA TEMPLATES ───────────────────────────────────
with tab_templates:
    st.markdown("### 💊 Pharma Event Templates")
    st.caption("Pre-built GA4 event templates for common pharma website interactions. Select and add to your SDR.")

    templates = list_pharma_templates()

    col1, col2 = st.columns([3, 1])
    with col1:
        selected_templates = st.multiselect(
            "Select templates to add",
            templates,
            default=["ISI Scroll Tracking", "Patient Support & Copay"],
            help="Select one or more templates to preview and add to your SDR"
        )
    with col2:
        add_clicked = st.button("➕ Add to SDR", type="primary", width='stretch', key="add_templates")

    if selected_templates:
        preview_rows = []
        for t in selected_templates:
            preview_rows.extend(get_pharma_template(t))
        st.markdown(f"**Preview — {len(preview_rows)} events from {len(selected_templates)} template(s):**")
        st.dataframe(
            pd.DataFrame(preview_rows)[["Category", "Event Name", "Action", "Label", "Business Intent"]],
            width='stretch', hide_index=True
        )

    if add_clicked and selected_templates:
        new_rows = []
        for t in selected_templates:
            new_rows.extend(get_pharma_template(t))
        existing = st.session_state.get("sdr_rows", [])
        existing_keys = {(r.get("Category"), r.get("Event Name")) for r in existing}
        added = [r for r in new_rows if (r["Category"], r["Event Name"]) not in existing_keys]
        st.session_state["sdr_rows"] = existing + added
        if added:
            st.success(f"✅ Added {len(added)} new events to your SDR. Go to Manual Entry or Auto Scan tab to view and export.")
        else:
            st.info("All selected template events already exist in your SDR.")

    st.divider()
    st.markdown("#### 📋 All Available Templates")
    for tname in templates:
        with st.expander(f"**{tname}** — {len(get_pharma_template(tname))} events"):
            st.dataframe(
                pd.DataFrame(get_pharma_template(tname))[["Category", "Event Name", "Action", "Label", "Business Intent"]],
                width='stretch', hide_index=True
            )

# ── TAB 4: HOW IT WORKS ──────────────────────────────────────
with tab_howto:
    st.markdown("""
### 📖 How This Tool Works
This is an **AI-assisted SDR generator** — not a fully automated scraper.

#### 🔍 Auto Scan — Multi-Page Support
Enter **multiple URLs** (one per line) — homepage, HCP page, patient page, condition page.
All pages are scanned and merged into one deduplicated SDR.

#### ⚡ 5-Strategy Scanning Engine
| # | Strategy | Works On |
|---|---------|---------|
| 1 | curl_cffi | Most pharma, e-commerce — Chrome TLS fingerprint |
| 2 | requests | Open / lightly protected sites |
| 3 | Playwright | JS-heavy SPAs, React sites, cookie banners |
| 4 | ScraperAPI | Incapsula / Cloudflare Enterprise (needs API key) |
| 5 | Google Cache | Last resort fallback |

#### 📋 ISI Auto-Detection
If the scanner detects ISI-related content (Important Safety Information, indications, warnings),
it automatically generates 4 scroll depth events: `scroll_isi_25/50/75/100`.

#### 💊 Pharma Templates
Pre-built event templates for 7 common pharma tracking scenarios:
ISI Scroll, Condition Selector, Patient Support, Find a Doctor, HCP Site, Video, Page Scroll.
Add them in one click and edit in the Manual Entry tab.

#### 🔑 For Incapsula-Protected Sites (opzelura.com etc.)
Get a free ScraperAPI key at scraperapi.com (5,000 free requests/month) and paste in sidebar.

#### 📤 Export Formats
- **CSV** — Standard SDR for stakeholders
- **GA4 JSON** — Measurement Protocol-compatible
- **GTM dataLayer JS** — Paste-ready GTM snippets
""")
