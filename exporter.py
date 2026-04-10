import json
import pandas as pd


def to_csv(rows: list) -> str:
    if not rows:
        return ""
    df = pd.DataFrame(rows)
    return df.to_csv(index=False)


def to_ga4_json(rows: list) -> str:
    events = []
    for row in rows:
        events.append({
            "name": row.get("Event Name", ""),
            "params": {
                "event_category": row.get("Category", ""),
                "event_action":   row.get("Action", ""),
                "event_label":    row.get("Label", ""),
                "business_intent": row.get("Business Intent", ""),
            }
        })
    return json.dumps({"events": events}, indent=2)


def to_gtm_datalayer(rows: list) -> str:
    lines = ["// GTM dataLayer snippets — paste into GTM Custom HTML tag\n"]
    for row in rows:
        snippet = (
            f"// {row.get('Element Type', '')} | {row.get('Label', '')[:60]}\n"
            f"dataLayer.push({{\n"
            f"  event: '{row.get('Event Name', '')}',\n"
            f"  eventCategory: '{row.get('Category', '')}',\n"
            f"  eventAction: '{row.get('Action', '')}',\n"
            f"  eventLabel: '{str(row.get('Label', '')).replace(chr(39), '')}',\n"
            f"  businessIntent: '{row.get('Business Intent', '')}'\n"
            f"}});\n"
        )
        lines.append(snippet)
    return "\n".join(lines)
