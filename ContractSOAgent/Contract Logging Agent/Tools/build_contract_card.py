"""
Tool: build_contract_card.py
Purpose: Prepare contract details and Adaptive Cards for the Teams Contract logging flow.
"""

import re
from datetime import datetime, timedelta

DIVISION_PRODUCTS = {
    "CRCA":         ["CRCA Coil - (S_CRCACF)", "CRCA Sheet - (S_CRCASF)"],
    "GI":           ["GI Coil - (S_GICF)", "GI Sheet - (S_GISF)", "HR GI Coil - (S_HRGICF)", "ZM Coil - (S_ZMCF)"],
    "GL":           ["GL Coil - (S_GLCF)"],
    "HRC":          ["HR Coil - (S_HRCF)", "HR Sheet & Plate - (S_HRCTLF)"],
    "HRPO":         ["HRPO Coil - (S_HRPKLCF)", "HRPO Sheet - (S_HRPKLSF)"],
    "PPGI":         ["PPGI Coil - (S_PPGICF)", "PPGI Sheet - (S_PPGISF)"],
    "PPGL":         ["PPGL Coil - (S_PPGLCF)", "PPGL Sheet - (S_PPGLSF)"],
    "TFS Product":  ["TFS Coil - (S_ECCSCF)"],
    "TMBP Product": ["TMBP Sheet - (S_TMBPSF)", "TMBP SR Coil - (S_TMBPSRCF)", "TMBP DR Coil - (S_TMBPDRCF)"],
    "TMBP":         ["TMBP Sheet - (S_TMBPSF)", "TMBP SR Coil - (S_TMBPSRCF)", "TMBP DR Coil - (S_TMBPDRCF)"],
    "TMT":          ["TMT Bar - (S_TMTBF)", "TMT Bar CBF - (S_TMTBCBF)", "TMT Coil - (S_TMTCF)"],
    "TPS Product":  ["TPS Coil - (S_ELTPCF)", "TPS Sheet - (S_ELTPSF)"],
    "WR":           ["WR Coil - (S_WRCF)"],
    "ZM":           ["ZM Coil - (S_ZMCF)"],
}

SKU_PRODUCT_BY_MATERIAL = {
    "HRC": {
        "S_HRCF": "HR Coil - (S_HRCF)",
        "S_HRCTLF": "HR Sheet & Plate - (S_HRCTLF)",
    },
    "CRCA": {
        "S_CRCACF": "CRCA Coil - (S_CRCACF)",
        "S_CRCASF": "CRCA Sheet - (S_CRCASF)",
    },
    "GI": {
        "S_GICF": "GI Coil - (S_GICF)",
        "S_GISF": "GI Sheet - (S_GISF)",
        "S_HRGICF": "HR GI Coil - (S_HRGICF)",
        "S_ZMCF": "ZM Coil - (S_ZMCF)",
    },
}

SKU_DETAIL_FIELDS = {
    "HRC": {
        "default": [
            ("customer_order_category", "Customer Order Category"),
            ("eq_specif_grp", "Eq. Specification Group"),
            ("eq_specifi", "Eq. Specification"),
            ("eq_sub_grade", "Eq. Sub Specification"),
            ("end_appn", "End Application"),
            ("rh_req", "RH REQ"),
            ("plant_code", "Supply Plant / Depot"),
            ("cust_req_date", "Customer Requested Date"),
            ("width", "Width"),
            ("thickness", "Thickness"),
            ("edge_con", "Edge Condition"),
        ],
        "S_HRCTLF": [
            ("customer_order_category", "Customer Order Category"),
            ("eq_specif_grp", "Eq. Specification Group"),
            ("eq_specifi", "Eq. Specification"),
            ("eq_sub_grade", "Eq. Sub Specification"),
            ("end_appn", "End Application"),
            ("rh_req", "RH REQ"),
            ("plant_code", "Supply Plant / Depot"),
            ("cust_req_date", "Customer Requested Date"),
            ("width", "Width"),
            ("thickness", "Thickness"),
            ("length", "Length"),
            ("edge_con", "Edge Condition"),
        ],
    },
    "CRCA": {
        "default": [
            ("customer_order_category", "Customer Order Category"),
            ("eq_specif_grp", "Eq. Specification Group"),
            ("eq_specifi", "Eq. Specification"),
            ("eq_sub_grade", "Eq. Sub Specification"),
            ("end_appn", "End Application"),
            ("plant_code", "Supply Plant / Depot"),
            ("cust_req_date", "Customer Requested Date"),
            ("width", "Width"),
            ("thickness", "Thickness"),
            ("thick_tol_type", "Thickness Tolerance Type"),
            ("oil_req", "Oil Required"),
        ],
        "S_CRCACF": [
            ("customer_order_category", "Customer Order Category"),
            ("eq_specif_grp", "Eq. Specification Group"),
            ("eq_specifi", "Eq. Specification"),
            ("eq_sub_grade", "Eq. Sub Specification"),
            ("end_appn", "End Application"),
            ("plant_code", "Supply Plant / Depot"),
            ("cust_req_date", "Customer Requested Date"),
            ("width", "Width"),
            ("thickness", "Thickness"),
            ("thick_tol_type", "Thickness Tolerance Type"),
            ("edge_con", "Edge Condition"),
            ("oil_req", "Oil Required"),
        ],
        "S_CRCASF": [
            ("customer_order_category", "Customer Order Category"),
            ("eq_specif_grp", "Eq. Specification Group"),
            ("eq_specifi", "Eq. Specification"),
            ("eq_sub_grade", "Eq. Sub Specification"),
            ("end_appn", "End Application"),
            ("plant_code", "Supply Plant / Depot"),
            ("cust_req_date", "Customer Requested Date"),
            ("width", "Width"),
            ("thickness", "Thickness"),
            ("length", "Length"),
            ("thick_tol_type", "Thickness Tolerance Type"),
            ("oil_req", "Oil Required"),
        ],
    },
    "GI": {
        "default": [
            ("customer_order_category", "Customer Order Category"),
            ("eq_specif_grp", "Eq. Specification Group"),
            ("eq_specifi", "Eq. Specification"),
            ("eq_sub_grade", "Eq. Sub Specification"),
            ("end_appn", "End Application"),
            ("rh_req", "RH REQ"),
            ("plant_code", "Supply Plant / Depot"),
            ("cust_req_date", "Customer Requested Date"),
            ("width", "Width"),
            ("thickness", "Thickness"),
            ("thick_tol_type", "Thickness Tolerance Type"),
            ("edge_con", "Edge Condition"),
            ("oil_req", "Oil Required"),
        ],
        "S_GISF": [
            ("customer_order_category", "Customer Order Category"),
            ("eq_specif_grp", "Eq. Specification Group"),
            ("eq_specifi", "Eq. Specification"),
            ("eq_sub_grade", "Eq. Sub Specification"),
            ("end_appn", "End Application"),
            ("rh_req", "RH REQ"),
            ("plant_code", "Supply Plant / Depot"),
            ("cust_req_date", "Customer Requested Date"),
            ("width", "Width"),
            ("thickness", "Thickness"),
            ("length", "Length"),
            ("thick_tol_type", "Thickness Tolerance Type"),
            ("edge_con", "Edge Condition"),
            ("oil_req", "Oil Required"),
        ],
    },
}


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
    ship_plant_code = (
        get_cf("Ship Plant Code")
        or get_cf("SHIP Plant Code")
        or get_cf("SHIP PLANT")
        or get_cf("Ship Plant")
        or get_cf("Plant Code")
        or get_cf("Plant Name")
    )
    po_number = get_cf("PO Number")
    po_date = normalise_date(get_cf("PO Date"))
    customer_requested_delivery_date = normalise_date(
        get_cf("Customer Requested Delivery Date")
        or get_cf("Customer Requested Date")
    )

    return {
        "ticket_id": ticket.get("key", ""),
        "contract_type": derive_contract_type(customer_type, plant_type),
        "contract_source": "Standard",
        "sold_to_party": strip_leading_zeroes(sold_to_raw),
        "ship_to_party": strip_leading_zeroes(ship_to_raw),
        "payer": "40101601" if payer_code.strip().upper() == "JODL" else "40102336",
        "division": product_type,
        "ship_plant_code": extract_plant_code(ship_plant_code),
        "distribution_channel": "",
        "po_number": po_number,
        "po_date": po_date,
        "contract_end_date": calc_end_date(po_date, days=90),
        "customer_requested_delivery_date": customer_requested_delivery_date,
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
            hidden_text("ship_plant_code", data.get("ship_plant_code", "")),
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


def build_contract_creation_failed_card(ticket_id: str, error_message: str) -> dict:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"Sorry, Not able to create new contract for {ticket_id} due to this error.",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Attention",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Jira Ticket", "value": ticket_id or "-"},
                    {"title": "Status", "value": "Failed. Detailed error is available in Cloud Run logs."},
                ],
            },
        ],
    }


def build_contract_validation_failed_card(ticket_id: str, missing_fields: list[str]) -> dict:
    fields = ", ".join(missing_fields)
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"Please fill {fields} before confirming {ticket_id}.",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Attention",
                "wrap": True,
            }
        ],
    }


def build_contract_creation_started_card(ticket_id: str) -> dict:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": (
                    f"Creating Contract on JSW Steel Salesforce for {ticket_id}. "
                    "I will post the Contract number card to this channel shortly."
                ),
                "weight": "Bolder",
                "size": "Medium",
                "color": "Accent",
                "wrap": True,
            }
        ],
    }


def build_sku_card(contract_number: str, division: str = "") -> dict:
    """Adaptive Card for user to fill SKU line item details."""
    product_choices = DIVISION_PRODUCTS.get(division, [])
    if product_choices:
        product_name_field = {
            "type": "Input.ChoiceSet",
            "id": "product_name",
            "label": "Product Name",
            "style": "compact",
            "value": "",
            "isRequired": True,
            "choices": [{"title": name, "value": name} for name in product_choices],
        }
    else:
        product_name_field = input_text(
            "product_name",
            "Product Name (Division not recognised — enter manually, e.g. HR Coil - (S_HRCF))",
            "",
        )

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"SKU Line Item — Contract {contract_number}",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Accent",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "Fill in the SKU details and click Confirm.",
                "wrap": True,
                "spacing": "Small",
                "isSubtle": True,
            },
            {
                "type": "TextBlock",
                "text": f"Division: {division or 'Unknown'}",
                "spacing": "Small",
                "isSubtle": True,
            },
            {"type": "Input.Text", "id": "contract_number", "value": contract_number, "isVisible": False},
            {"type": "Input.Text", "id": "division", "value": division, "isVisible": False},
            product_name_field,
            input_text("customer_order_category", "Customer Order Category (e.g. STD)", ""),
            input_text("sku_description", "SKU Description / Part Number (e.g. 1.6X1060-P1-10748_2004-GR2)", ""),
            input_text("eq_specif_grp", "Eq. Specification Group (e.g. BIS)", ""),
            input_text("eq_specifi", "Eq. Specification (e.g. 10748_2004)", ""),
            input_text("eq_sub_grade", "Eq. Sub Grade (e.g. GR2)", ""),
            input_text("end_appn", "End Application (e.g. P&T)", ""),
            input_text("order_qty", "Order Quantity (e.g. 100)", ""),
            input_text("cust_req_date", "Customer Requested Date (DD/MM/YYYY)", ""),
            input_text("width", "Width (e.g. 1060.000)", ""),
            input_text("thickness", "Thickness (e.g. 1.600)", ""),
            input_text("edge_con", "Edge Condition (e.g. ME)", ""),
            input_text("plant_code", "Plant Code (e.g. 1001 - Vijayanagar Works)", ""),
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Confirm",
                "data": {"contract_number": contract_number},
            }
        ],
    }


def build_sku_success_card(contract_number: str, line_name: str) -> dict:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"SKU line item added successfully to contract {contract_number}.",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Good",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Contract Number", "value": contract_number},
                    {"title": "Line Item Name", "value": line_name or "-"},
                ],
            },
        ],
    }


def build_sku_failure_card(contract_number: str, error: str) -> dict:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"Could not add SKU line item to contract {contract_number}.",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Attention",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Contract Number", "value": contract_number},
                    {"title": "Error", "value": (error or "-")[:500]},
                ],
            },
        ],
    }


def build_hrc_sku_line_created_card(contract_number: str, line_name: str, details: dict) -> dict:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": (
                    f"SKU added successfully in contract {contract_number}. "
                    "Here is the Contract Line Item."
                ),
                "weight": "Bolder",
                "size": "Medium",
                "color": "Good",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Contract Number", "value": contract_number or "-"},
                    {"title": "Contract Line Item", "value": line_name or "-"},
                    {"title": "Material", "value": details.get("material") or "-"},
                    {"title": "SKU", "value": details.get("description") or "-"},
                    {"title": "Qty", "value": details.get("qty") or "-"},
                ],
            },
        ],
    }


def build_hrc_sku_selection_card(context: dict, lookup: dict) -> dict:
    """First SKU card: material, SKU/description, and quantity."""
    contract_number = context.get("contract_number", "")
    division = (context.get("division") or "HRC").strip().upper()
    materials = lookup.get("materials") or _materials_from_skus(lookup.get("skus", []))
    skus = lookup.get("skus") or lookup.get("descriptions") or lookup.get("rows") or []
    if not materials:
        materials = _materials_from_skus(skus)
    material_choices = _choices(materials)
    sku_choices = _sku_choices(skus)

    if not material_choices:
        material_choices = [
            {"title": material, "value": material}
            for material in SKU_PRODUCT_BY_MATERIAL.get(division, SKU_PRODUCT_BY_MATERIAL["HRC"])
        ]

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"Add {division} SKU Details - Contract {contract_number}",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Accent",
                "wrap": True,
            },
            {"type": "FactSet", "facts": [
                {"title": "Contract Number", "value": contract_number or "-"},
                {"title": "Division", "value": division or "-"},
                {"title": "Jira Ticket", "value": context.get("ticket_id") or "-"},
                {"title": "B P Code", "value": context.get("sold_to_party") or "-"},
                {"title": "S P Code", "value": context.get("ship_to_party") or "-"},
                {"title": "SHIP Plant Code", "value": context.get("ship_plant_code") or "-"},
            ]},
            hidden_text("contract_number", contract_number),
            hidden_text("ticket_id", context.get("ticket_id", "")),
            hidden_text("division", division),
            hidden_text("bp_code", context.get("sold_to_party", "")),
            hidden_text("sp_code", context.get("ship_to_party", "")),
            hidden_text("ship_plant_code", context.get("ship_plant_code", "")),
            {
                "type": "Input.ChoiceSet",
                "id": "material",
                "label": "Material Type",
                "style": "compact",
                "choices": material_choices,
            },
            {
                "type": "Input.ChoiceSet",
                "id": "description",
                "label": "SKU / Description",
                "style": "compact",
                "choices": sku_choices,
            } if sku_choices else input_text("description", "SKU / Description", ""),
            input_text("qty", "Qty", ""),
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Confirm",
                "data": {"contract_number": contract_number, "stage": f"{division.lower()}_sku_select"},
            }
        ],
    }


def build_hrc_sku_row_choice_card(context: dict, selection: dict, rows: list[dict], request_id: str) -> dict:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"Multiple {(context.get('division') or 'SKU').upper()} rows matched contract {context.get('contract_number', '')}",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Accent",
                "wrap": True,
            },
            {"type": "TextBlock", "text": "Select the correct row, then confirm.", "wrap": True},
            hidden_text("request_id", request_id),
            hidden_text("contract_number", context.get("contract_number", "")),
            {
                "type": "Input.ChoiceSet",
                "id": "row_index",
                "label": "Matching Row",
                "style": "compact",
                "choices": [
                    {"title": _row_choice_title(row, index), "value": str(index)}
                    for index, row in enumerate(rows)
                ],
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Confirm Row",
                "data": {"request_id": request_id, "stage": "hrc_sku_row_choice"},
            }
        ],
    }


def build_hrc_sku_details_card(
    context: dict,
    selection: dict,
    details: dict,
    request_id: str,
) -> dict:
    material = selection.get("material", "")
    division = (context.get("division") or "HRC").strip().upper()
    fields = _sku_detail_fields(division, material)
    body = [
        {
            "type": "TextBlock",
            "text": f"Confirm {division} SKU Details - Contract {context.get('contract_number', '')}",
            "weight": "Bolder",
            "size": "Medium",
            "color": "Accent",
            "wrap": True,
        },
        {"type": "FactSet", "facts": [
            {"title": "Material", "value": material or "-"},
            {"title": "SKU", "value": selection.get("description") or "-"},
            {"title": "Qty", "value": selection.get("qty") or "-"},
        ]},
        hidden_text("request_id", request_id),
        hidden_text("contract_number", context.get("contract_number", "")),
        hidden_text("ticket_id", context.get("ticket_id", "")),
        hidden_text("division", division),
        hidden_text("bp_code", context.get("sold_to_party", "")),
        hidden_text("sp_code", context.get("ship_to_party", "")),
        hidden_text("material", material),
        hidden_text("description", selection.get("description", "")),
        hidden_text("qty", selection.get("qty", "")),
    ]
    for field_id, label in fields:
        body.append(input_text(field_id, label, str(details.get(field_id, "") or "")))

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": body,
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Confirm SKU Details",
                "data": {"request_id": request_id, "stage": f"{division.lower()}_sku_details"},
            }
        ],
    }


def build_hrc_sku_confirmed_card(contract_number: str, details: dict, context: dict | None = None) -> dict:
    context = context or {}
    division = (context.get("division") or details.get("division") or "HRC").strip().upper()
    material = (details.get("material") or "").strip()

    # Keep the core context visible for auditability.
    facts = [
        ("Jira Ticket", context.get("ticket_id") or details.get("ticket_id")),
        ("Contract Number", contract_number),
        ("Division", division),
        ("Sold to Party / B P Code", context.get("sold_to_party") or details.get("bp_code")),
        ("Ship to Party / S P Code", context.get("ship_to_party") or details.get("sp_code")),
        ("SHIP Plant Code", context.get("ship_plant_code") or details.get("plant_code")),
        ("Material", material),
        ("SKU / Description", details.get("description")),
        ("Qty", details.get("qty")),
    ]

    # Add only the parameter fields configured for this division/material.
    for field_id, label in _sku_detail_fields(division, material):
        value = details.get(field_id)
        if field_id == "plant_code" and not value:
            value = context.get("ship_plant_code")
        facts.append((label, value))

    filtered_facts = [
        {"title": label, "value": str(value).strip()}
        for label, value in facts
        if _has_meaningful_value(value)
    ]

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"You confirmed the following {division} SKU details for Contract - {contract_number}",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Good",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": (
                    f"Thanks for confirming. I am adding the SKU in contract {contract_number}. "
                    "I will share the Contract Line Item shortly."
                ),
                "wrap": True,
                "spacing": "Small",
            },
            {
                "type": "FactSet",
                "spacing": "Medium",
                "facts": filtered_facts,
            },
        ],
    }


def build_hrc_sku_validation_failed_card(message: str, contract_number: str = "") -> dict:
    suffix = f" for contract {contract_number}" if contract_number else ""
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            {
                "type": "TextBlock",
                "text": f"{message}{suffix}.",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Attention",
                "wrap": True,
            }
        ],
    }


def contract_facts(data: dict) -> list[dict]:
    labels = [
        ("Jira Ticket", "ticket_id"),
        ("Contract Type", "contract_type"),
        ("Contract Source", "contract_source"),
        ("Sold to Party", "sold_to_party"),
        ("Ship to Party", "ship_to_party"),
        ("SHIP Plant Code", "ship_plant_code"),
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


def hidden_text(field_id: str, value: str) -> dict:
    return {"type": "Input.Text", "id": field_id, "value": value or "", "isVisible": False}


def _choices(values: list) -> list[dict]:
    seen = set()
    choices = []
    for value in values:
        text = _choice_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        choices.append({"title": text, "value": text})
    return choices


def _choice_text(value) -> str:
    if isinstance(value, dict):
        return _row_get(
            value,
            "material",
            "MATERIAL",
            "Material",
            "value",
            "description",
            "DESCRIPTION",
            "sku",
            "SKU",
        )
    return str(value or "").strip()


def _materials_from_skus(skus: list[dict]) -> list[str]:
    materials = []
    for item in skus:
        if isinstance(item, dict):
            materials.append(_row_get(item, "material", "MATERIAL", "Material"))
    return [material for material in materials if material]


def _sku_choices(skus: list[dict]) -> list[dict]:
    choices = []
    seen = set()
    for item in skus:
        if isinstance(item, dict):
            material = _row_get(item, "material", "MATERIAL", "Material")
            description = _row_get(item, "description", "DESCRIPTION", "Description", "sku", "SKU", "SKU_DESCRIPTION")
        else:
            material = ""
            description = str(item or "").strip()
        if not description:
            continue
        key = (material, description)
        if key in seen:
            continue
        seen.add(key)
        title = f"{material} | {description}" if material else description
        choices.append({"title": title[:120], "value": description})
    return choices[:200]


def _row_choice_title(row: dict, index: int) -> str:
    material = _row_get(row, "MATERIAL", "material")
    desc = _row_get(row, "DESCRIPTION", "description")
    so_item = _row_get(row, "SO ITEM", "so_item")
    plant = _row_get(row, "SHIP PLANT", "plant", "plant_code")
    parts = [str(index + 1), material, desc, so_item, plant]
    return " | ".join([p for p in parts if p])[:120]


def _row_get(row: dict, *keys: str) -> str:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
        value = lowered.get(key.strip().lower())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _has_meaningful_value(value) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return text.lower() not in {"-", ".", "--none--", "none", "null", "nan"}


def _sku_detail_fields(division: str, material: str) -> list[tuple[str, str]]:
    division_key = str(division or "HRC").strip().upper()
    material_key = str(material or "").strip().upper()
    fields_by_material = SKU_DETAIL_FIELDS.get(division_key, SKU_DETAIL_FIELDS["HRC"])
    return fields_by_material.get(material_key) or fields_by_material["default"]


def _hrc_detail_fields(material: str) -> list[tuple[str, str]]:
    return _sku_detail_fields("HRC", material)


def strip_leading_zeroes(value: str) -> str:
    return value.lstrip("0") or value


def extract_plant_code(value: str) -> str:
    text = str(value or "").strip()
    match = re.search(r"\d+", text)
    return match.group(0) if match else text


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
