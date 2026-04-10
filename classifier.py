import re

GUID_MAP = {
    r"first.?name|fname":      "first_name",
    r"last.?name|lname":       "last_name",
    r"full.?name":             "full_name",
    r"email|e.mail":           "email_address",
    r"phone|mobile|tel":       "phone_number",
    r"zip|postal":             "postal_code",
    r"city":                   "city",
    r"state|province":         "state",
    r"country":                "country",
    r"address|addr":           "address",
    r"company|organization":   "company_name",
    r"job.?title|role":        "job_title",
    r"message|comment|notes":  "message",
    r"password|pwd":           "password",
    r"dob|birth|date.?of":     "date_of_birth",
    r"specialty|speciality":   "specialty",
    r"npi":                    "npi_number",
    r"username|user.?name":    "username",
    r"search|query":           "search_query",
    r"subject":                "subject",
}


def _humanize_field(name):
    if not name:
        return "field"
    lower = name.lower()
    for pattern, label in GUID_MAP.items():
        if re.search(pattern, lower):
            return label
    if re.match(r"^[a-f0-9\-]{10,}$", lower) or len(lower) > 60:
        return "form_field"
    return name.replace("-", " ").replace("_", " ").strip()


def _infer_intent(el_type, text, purpose):
    t = (text + " " + purpose).lower()
    if el_type == "form" and purpose in ("registration", "lead_generation", "checkout"):
        return "conversion"
    if el_type == "form" and purpose == "newsletter":
        return "acquisition"
    if el_type == "form" and purpose == "contact":
        return "lead_nurture"
    if el_type in ("download", "video"):
        return "consideration"
    if el_type in ("external_link", "exit"):
        return "exit"
    if any(k in t for k in ["buy","order","checkout","purchase","enroll","register","get started","trial","demo","request","book","virtual appt","talk to a doctor","sign up","copay","savings","find a doctor","locate","patient support","schedule"]):
        return "conversion"
    if any(k in t for k in ["subscribe","newsletter","join","sign up for updates","register for updates"]):
        return "acquisition"
    if any(k in t for k in ["learn more","read","watch","view","explore","discover"]):
        return "consideration"
    if any(k in t for k in ["contact","support","help","faq","chat"]):
        return "support"
    if any(k in t for k in ["login","sign in","account","dashboard","portal"]):
        return "retention"
    return "engagement"


def _make_event_name(el_type, text, purpose):
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower().strip()).strip("_")[:40]
    if el_type == "form":
        return f"form_submit_{purpose}" if purpose else "form_submit"
    if el_type == "form_field":
        return f"form_field_{slug}"
    if el_type == "download":
        return f"file_download_{slug[:30]}"
    if el_type in ("link", "navigation"):
        return f"click_{slug}"
    if el_type == "external_link":
        return f"exit_click_{slug}"
    if el_type == "button":
        return f"cta_click_{slug}"
    if el_type == "video":
        return "video_play"
    return f"interaction_{slug}"


CONVERSION_CTA_KEYWORDS = [
    "book", "virtual appt", "talk to a doctor", "sign up", "register",
    "copay", "savings", "enroll", "get started", "patient support",
    "find a doctor", "schedule", "request", "demo", "trial", "buy"
]


def _fix_category(category, intent, text):
    t = text.lower()
    if intent == "conversion":
        return "conversion"
    if intent == "acquisition" and category == "navigation":
        return "conversion"
    if any(k in t for k in CONVERSION_CTA_KEYWORDS):
        return "conversion"
    return category


def classify_elements(elements, options=None):
    options = options or {}
    rows, seen = [], set()
    type_filter = {
        "link":          options.get("track_links", True),
        "external_link": options.get("track_exit", True),
        "download":      options.get("track_downloads", True),
        "form":          options.get("track_forms", True),
        "form_field":    options.get("track_forms", True),
        "video":         options.get("track_videos", True),
        "button":        options.get("track_buttons", True),
    }
    for el in elements:
        el_type = el.get("type", "link")
        if not type_filter.get(el_type, True):
            continue
        text    = el.get("text", "")
        purpose = el.get("purpose", "")
        if el_type == "form_field":
            text = _humanize_field(text)
        event_name = _make_event_name(el_type, text, purpose)
        intent     = _infer_intent(el_type, text, purpose)
        if el_type == "form":
            category = "conversion" if intent == "conversion" else "form_interaction"
            action   = "submit"
            label    = f"{purpose}_form" if purpose else "form"
        elif el_type == "form_field":
            category = "form_interaction"
            action   = "field_interaction"
            label    = text
        elif el_type == "download":
            category = "download"
            action   = "click"
            label    = el.get("href", text).split("/")[-1][:80]
        elif el_type == "external_link":
            category = "exit"
            action   = "click"
            label    = el.get("href", text)[:80]
        elif el_type == "button":
            category = "ui_interaction"
            action   = "click"
            label    = text[:80]
        elif el_type == "video":
            category = "engagement"
            action   = "play"
            label    = text[:80]
        else:
            category = "navigation"
            action   = "click"
            label    = text[:80]
        dedup_key = (category, event_name, label[:40])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        rows.append({
            "Category":        _fix_category(category, intent, text),
            "Event Name":      event_name,
            "Action":          action,
            "Label":           label,
            "Business Intent": intent,
            "Element Type":    el_type,
            "Source":          el.get("source", ""),
            "Notes":           "",
        })
    return rows


def enrich_with_llm(rows, api_key, provider):
    if not api_key or not rows:
        return rows
    import json
    import urllib.request
    try:
        sample = rows[:20]
        prompt = (
            "You are a GA4 analytics expert. Review these SDR rows and improve "
            "Event Name (GA4 snake_case max 40 chars) and Business Intent "
            "(one of: conversion, acquisition, consideration, awareness, "
            "retention, engagement, lead_nurture, support, discovery, exit).\n\n"
            "Return ONLY a JSON array with the same number of objects, "
            "each having keys Event Name and Business Intent.\n\n"
            f"Rows:\n{json.dumps(sample, indent=2)}"
        )
        if provider == "groq":
            endpoint = "https://api.groq.com/openai/v1/chat/completions"
            model    = "llama3-8b-8192"
        else:
            endpoint = "https://api.openai.com/v1/chat/completions"
            model    = "gpt-4o-mini"
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }).encode()
        req = urllib.request.Request(
            endpoint, data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        content     = data["choices"][0]["message"]["content"]
        json_match  = re.search(r"\[.*\]", content, re.DOTALL)
        if json_match:
            enriched = json.loads(json_match.group())
            for i, row in enumerate(sample):
                if i < len(enriched):
                    row["Event Name"]      = enriched[i].get("Event Name",      row["Event Name"])
                    row["Business Intent"] = enriched[i].get("Business Intent", row["Business Intent"])
    except Exception as e:
        print(f"[LLM] Enrichment failed: {e}")
    return rows


# ── ISI Scroll Auto-Detection ─────────────────────────────────

ISI_KEYWORDS = [
    "important safety", "isi", "safety information", "indications and usage",
    "warnings", "contraindications", "adverse reactions", "full prescribing"
]

def generate_isi_events(elements):
    has_isi = any(
        any(k in (e.get("text","") + e.get("href","")).lower() for k in ISI_KEYWORDS)
        for e in elements
    )
    if not has_isi:
        return []
    return [
        {"Category": "engagement", "Event Name": "scroll_isi_25",  "Action": "scroll", "Label": "ISI Section 25%",  "Business Intent": "awareness", "Element Type": "scroll", "Source": "auto_isi", "Notes": "Auto-generated: ISI section detected"},
        {"Category": "engagement", "Event Name": "scroll_isi_50",  "Action": "scroll", "Label": "ISI Section 50%",  "Business Intent": "awareness", "Element Type": "scroll", "Source": "auto_isi", "Notes": "Auto-generated: ISI section detected"},
        {"Category": "engagement", "Event Name": "scroll_isi_75",  "Action": "scroll", "Label": "ISI Section 75%",  "Business Intent": "awareness", "Element Type": "scroll", "Source": "auto_isi", "Notes": "Auto-generated: ISI section detected"},
        {"Category": "engagement", "Event Name": "scroll_isi_100", "Action": "scroll", "Label": "ISI Section 100%", "Business Intent": "awareness", "Element Type": "scroll", "Source": "auto_isi", "Notes": "Auto-generated: ISI section detected"},
    ]


# ── Pharma Event Templates ────────────────────────────────────

PHARMA_TEMPLATES = {
    "ISI Scroll Tracking": [
        {"Category": "engagement",   "Event Name": "scroll_isi_25",            "Action": "scroll", "Label": "ISI Section 25%",              "Business Intent": "awareness",     "Element Type": "scroll",   "Source": "template", "Notes": ""},
        {"Category": "engagement",   "Event Name": "scroll_isi_50",            "Action": "scroll", "Label": "ISI Section 50%",              "Business Intent": "awareness",     "Element Type": "scroll",   "Source": "template", "Notes": ""},
        {"Category": "engagement",   "Event Name": "scroll_isi_75",            "Action": "scroll", "Label": "ISI Section 75%",              "Business Intent": "awareness",     "Element Type": "scroll",   "Source": "template", "Notes": ""},
        {"Category": "engagement",   "Event Name": "scroll_isi_100",           "Action": "scroll", "Label": "ISI Section 100%",             "Business Intent": "awareness",     "Element Type": "scroll",   "Source": "template", "Notes": ""},
    ],
    "Condition Selector": [
        {"Category": "navigation",   "Event Name": "click_condition_selector", "Action": "click",  "Label": "Condition Selector Dropdown",  "Business Intent": "consideration", "Element Type": "button",   "Source": "template", "Notes": ""},
        {"Category": "navigation",   "Event Name": "select_condition_eczema",  "Action": "select", "Label": "Atopic Dermatitis / Eczema",   "Business Intent": "consideration", "Element Type": "dropdown", "Source": "template", "Notes": ""},
        {"Category": "navigation",   "Event Name": "select_condition_vitiligo","Action": "select", "Label": "Nonsegmental Vitiligo",        "Business Intent": "consideration", "Element Type": "dropdown", "Source": "template", "Notes": ""},
    ],
    "Patient Support & Copay": [
        {"Category": "conversion",   "Event Name": "click_patient_support",    "Action": "click",  "Label": "Patient Support Program",      "Business Intent": "conversion",    "Element Type": "link",     "Source": "template", "Notes": ""},
        {"Category": "conversion",   "Event Name": "click_copay_card",         "Action": "click",  "Label": "Copay Savings Card",           "Business Intent": "conversion",    "Element Type": "link",     "Source": "template", "Notes": ""},
        {"Category": "conversion",   "Event Name": "form_submit_copay",        "Action": "submit", "Label": "copay_form",                   "Business Intent": "conversion",    "Element Type": "form",     "Source": "template", "Notes": ""},
        {"Category": "conversion",   "Event Name": "click_patient_enrollment", "Action": "click",  "Label": "Enroll in Patient Program",    "Business Intent": "conversion",    "Element Type": "button",   "Source": "template", "Notes": ""},
    ],
    "Find a Doctor / Locator": [
        {"Category": "conversion",   "Event Name": "click_find_doctor",        "Action": "click",  "Label": "Find a Doctor / Locator",      "Business Intent": "conversion",    "Element Type": "button",   "Source": "template", "Notes": ""},
        {"Category": "conversion",   "Event Name": "form_submit_locator",      "Action": "submit", "Label": "Doctor Locator Search",        "Business Intent": "conversion",    "Element Type": "form",     "Source": "template", "Notes": ""},
        {"Category": "engagement",   "Event Name": "click_locator_result",     "Action": "click",  "Label": "Doctor Locator Result",        "Business Intent": "consideration", "Element Type": "link",     "Source": "template", "Notes": ""},
    ],
    "HCP Site Interactions": [
        {"Category": "exit",         "Event Name": "exit_click_hcp_site",      "Action": "click",  "Label": "Healthcare Professional Site", "Business Intent": "acquisition",   "Element Type": "link",     "Source": "template", "Notes": ""},
        {"Category": "conversion",   "Event Name": "form_submit_hcp_register", "Action": "submit", "Label": "HCP Registration Form",        "Business Intent": "acquisition",   "Element Type": "form",     "Source": "template", "Notes": ""},
        {"Category": "download",     "Event Name": "file_download_pi",         "Action": "click",  "Label": "Prescribing Information PDF",  "Business Intent": "consideration", "Element Type": "download", "Source": "template", "Notes": ""},
        {"Category": "download",     "Event Name": "file_download_moa_video",  "Action": "play",   "Label": "Mechanism of Action Video",    "Business Intent": "consideration", "Element Type": "video",    "Source": "template", "Notes": ""},
    ],
    "Video Engagement": [
        {"Category": "engagement",   "Event Name": "video_play",               "Action": "play",   "Label": "Video Start",                  "Business Intent": "consideration", "Element Type": "video",    "Source": "template", "Notes": ""},
        {"Category": "engagement",   "Event Name": "video_progress_50",        "Action": "progress","Label": "Video 50% Watched",           "Business Intent": "consideration", "Element Type": "video",    "Source": "template", "Notes": ""},
        {"Category": "engagement",   "Event Name": "video_complete",           "Action": "complete","Label": "Video 100% Complete",         "Business Intent": "consideration", "Element Type": "video",    "Source": "template", "Notes": ""},
    ],
    "Page Scroll Depth": [
        {"Category": "engagement",   "Event Name": "scroll_depth_25",          "Action": "scroll", "Label": "Page Scroll 25%",              "Business Intent": "engagement",    "Element Type": "scroll",   "Source": "template", "Notes": ""},
        {"Category": "engagement",   "Event Name": "scroll_depth_50",          "Action": "scroll", "Label": "Page Scroll 50%",              "Business Intent": "engagement",    "Element Type": "scroll",   "Source": "template", "Notes": ""},
        {"Category": "engagement",   "Event Name": "scroll_depth_75",          "Action": "scroll", "Label": "Page Scroll 75%",              "Business Intent": "engagement",    "Element Type": "scroll",   "Source": "template", "Notes": ""},
        {"Category": "engagement",   "Event Name": "scroll_depth_100",         "Action": "scroll", "Label": "Page Scroll 100%",             "Business Intent": "engagement",    "Element Type": "scroll",   "Source": "template", "Notes": ""},
    ],
}


def get_pharma_template(template_name):
    return PHARMA_TEMPLATES.get(template_name, [])


def list_pharma_templates():
    return list(PHARMA_TEMPLATES.keys())
