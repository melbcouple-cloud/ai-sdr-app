import json
import pandas as pd


def to_csv(rows: list) -> str:
    if not rows:
        return ""
    return pd.DataFrame(rows).to_csv(index=False)


def to_ga4_json(rows: list) -> str:
    events = []
    for idx, row in enumerate(rows, 1):
        events.append({
            "event_id": row.get("Event ID", f"ga{idx}"),
            "name":     row.get("Event Name", ""),
            "params": {
                "event_category":  row.get("Category", ""),
                "event_action":    row.get("Action", ""),
                "event_label":     row.get("Label", ""),
                "business_intent": row.get("Business Intent", ""),
                "cta_location":    row.get("CTA Location", ""),
                "cta_text":        row.get("CTA Text", ""),
                "page_url":        row.get("Page URL", ""),
            },
        })
    return json.dumps({"events": events}, indent=2, ensure_ascii=False)


def to_gtm_datalayer(rows: list) -> str:
    # FIX: json.dumps on every string value safely handles apostrophes,
    # quotes, backslashes and non-ASCII — replaces the old .replace(chr(39),'')
    lines = ["// GTM dataLayer snippets — paste into GTM Custom HTML tag\n"]
    for row in rows:
        snippet = (
            f"// {row.get('Element Type','')} | {str(row.get('Label',''))[:60]}\n"
            f"dataLayer.push({{\n"
            f"  event:          {json.dumps(row.get('Event Name',''))},\n"
            f"  eventCategory:  {json.dumps(row.get('Category',''))},\n"
            f"  eventAction:    {json.dumps(row.get('Action',''))},\n"
            f"  eventLabel:     {json.dumps(str(row.get('Label','')))},\n"
            f"  businessIntent: {json.dumps(row.get('Business Intent',''))},\n"
            f"  ctaLocation:    {json.dumps(row.get('CTA Location',''))},\n"
            f"  ctaText:        {json.dumps(str(row.get('CTA Text','')))}\n"
            f"}});\n"
        )
        lines.append(snippet)
    return "\n".join(lines)
