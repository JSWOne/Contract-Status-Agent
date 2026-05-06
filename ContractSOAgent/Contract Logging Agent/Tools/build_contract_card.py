"""
Tool: build_contract_card.py
Purpose: Prepare contract details and Adaptive Cards for the Teams Contract logging flow.
"""

from datetime import datetime, timedelta


def prepare_contract_details(ticket: dict) -> dict:
    fields = ticket.get("custom_fields", {})

    def get_cf(name: str) -> str:
        name_lower = name.lower()
        exact = next((v for k, v in fields.items() if k.strip().lower() == name_lower), "")
        if exact:
            return exact
        return next((v for k, v in fields.items() if name_lower in k.strip().lower()), "")

    customer_type = get_cf("Customer Type")
    plant_type = get_cf("Plant Type")
    sold_to_raw = get_cf("Sold to party code") or get_cf("Sold To Party Code")
    ship_to_raw = get_cf("Ship to party code") or get_cf("Ship To Party Code")
    payer_code = get_cf("Payer code")
    product_type = get_cf("Product Type")
    po_number = get_cf("PO Number")
    po_date = normalise_date(get_cf("PO Date"))

    return {
        "ticket_id": ticket.get("key", ""),
        "contract_type": derive_contract_type(customer_type, plant_type),
        "contract_source": "Standard",
        "sold_to_party": strip_leading_zeroes(sold_to_raw),
        "ship_to_party": strip_leading_zeroes(ship_to_raw),
        "payer": "40101601" if payer_code.strip().upper() == "JODL" else "40102336",
        "division": product_type,
        "distribution_channel": "",
        "po_number": po_number,
        "po_date": po_date,
        "contract_end_date": calc_end_date(po_date, days=90),
    }


def build_confirmation_card(data: dict) -> dict:
    ticket_id = data.get("ticket_id", "")
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"SO Contract Creation - {ticket_id}",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Accent",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "Verify and edit fields if needed, then confirm.",
                "wrap": True,
                "spacing": "Small",
                "isSubtle": True,
            },
            input_text("contract_type", "Contract Type", data.get("contract_type", "")),
            input_text("contract_source", "Contract Source", data.get("contract_source", "Standard")),
            input_text("sold_to_party", "Sold to Party", data.get("sold_to_party", "")),
            input_text("ship_to_party", "Ship to Party", data.get("ship_to_party", "")),
            input_text("payer", "Payer", data.get("payer", "")),
            input_text("division", "Division", data.get("division", "")),
            {
                "type": "Input.ChoiceSet",
                "id": "distribution_channel",
                "label": "Distribution Channel",
                "style": "compact",
                "value": data.get("distribution_channel", ""),
                "choices": [
                    {"title": "OEM", "value": "OEM"},
                    {"title": "MSME", "value": "MSME"},
                ],
            },
            input_text("po_number", "PO Number", data.get("po_number", "")),
            input_text("po_date", "PO Date (DD/MM/YYYY)", data.get("po_date", "")),
            input_text(
                "contract_end_date",
                "Contract End Date (DD/MM/YYYY)",
                data.get("contract_end_date", ""),
            ),
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Confirm",
                "data": {"ticket_id": ticket_id},
            }
        ],
    }


def build_audit_card(data: dict) -> dict:
    ticket_id = (data.get("ticket_id") or "").strip()
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"You confirmed the following details for SO Contract - {ticket_id}",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Good",
                "wrap": True,
            },
            {"type": "FactSet", "spacing": "Medium", "facts": contract_facts(data)},
        ],
    }


def build_navigation_success_card(ticket_id: str, url: str) -> dict:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"Successfully navigated to the Contract page for {ticket_id}.",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Good",
                "wrap": True,
            },
            {"type": "FactSet", "facts": [{"title": "Contract Page", "value": url}]},
        ],
    }


def build_contract_created_card(ticket_id: str, contract_number: str) -> dict:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": (
                    f"SO Contract created successfully on JSW Steel Community SF portal for {ticket_id}."
                ),
                "weight": "Bolder",
                "size": "Medium",
                "color": "Good",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Jira Ticket", "value": ticket_id},
                    {"title": "Contract Number", "value": contract_number or "-"},
                ],
            },
        ],
    }


def contract_facts(data: dict) -> list[dict]:
    labels = [
        ("Jira Ticket", "ticket_id"),
        ("Contract Type", "contract_type"),
        ("Contract Source", "contract_source"),
        ("Sold to Party", "sold_to_party"),
        ("Ship to Party", "ship_to_party"),
        ("Payer", "payer"),
        ("Division", "division"),
        ("Distribution Channel", "distribution_channel"),
        ("PO Number", "po_number"),
        ("PO Date", "po_date"),
        ("Contract End Date", "contract_end_date"),
    ]
    return [{"title": label, "value": str(data.get(key) or "-")} for label, key in labels]


def input_text(field_id: str, label: str, value: str) -> dict:
    return {"type": "Input.Text", "id": field_id, "label": label, "value": value or ""}


def strip_leading_zeroes(value: str) -> str:
    return value.lstrip("0") or value


def derive_contract_type(customer_type: str, plant_type: str) -> str:
    customer = customer_type.lower()
    plant = plant_type.lower()
    if "po" in customer and "plant" in plant:
        return "ZCQT"
    if "po" in customer and "yard" in plant:
        return "ZCQD"
    if "monthly" in customer and "plant" in plant:
        return "ZCQX"
    if "monthly" in customer and "yard" in plant:
        return "ZCDX"
    return ""


def normalise_date(raw: str) -> str:
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return raw.strip()


def calc_end_date(po_date: str, days: int = 90) -> str:
    if not po_date:
        return ""
    try:
        start = datetime.strptime(po_date, "%d/%m/%Y")
    except ValueError:
        return ""
    return (start + timedelta(days=days)).strftime("%d/%m/%Y")
