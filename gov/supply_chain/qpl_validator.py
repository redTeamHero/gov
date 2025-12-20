"""Supplier QPL/QML validation engine."""
from __future__ import annotations

from typing import Any, Dict, List

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_CONDITIONAL = "CONDITIONAL"


TRUE_VALUES = {"true", "yes", "required", "y"}


def _is_explicit_true(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, int) and value == 1:
        return True
    if isinstance(value, str):
        return value.strip().lower() in TRUE_VALUES
    return False


def _normalize_role(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _extract_nested_values(payload: Dict[str, Any], keys: List[str]) -> List[Any]:
    values = []
    for key in keys:
        if key in payload:
            values.append(payload.get(key))
    for section_key in ["requirements", "compliance", "source_approval", "snapshot", "key_facts"]:
        section = payload.get(section_key)
        if isinstance(section, dict):
            for key in keys:
                if key in section:
                    values.append(section.get(key))
    return values


def _flag_present(payload: Dict[str, Any], keys: List[str]) -> bool:
    for value in _extract_nested_values(payload, keys):
        if _is_explicit_true(value):
            return True
        if isinstance(value, str):
            normalized = value.strip().lower()
            if any(token in normalized for token in keys) and "required" in normalized:
                return True
    return False


def _requires_qpl_or_qml(rfq: Dict[str, Any]) -> bool:
    keys = [
        "qpl_required",
        "qml_required",
        "qpl",
        "qml",
        "qualified_products_list",
        "qualified_manufacturers_list",
    ]
    return _flag_present(rfq, keys)


def _requires_coqc(rfq: Dict[str, Any]) -> bool:
    keys = ["coqc_required", "coqc", "certificate_of_conformance"]
    return _flag_present(rfq, keys)


def _is_critical_application_item(rfq: Dict[str, Any]) -> bool:
    keys = ["critical_application_item", "cai"]
    return _flag_present(rfq, keys)


def _supplier_is_authorized_distributor(supplier: Dict[str, Any]) -> bool:
    if _is_explicit_true(supplier.get("authorized_distributor")):
        return True
    if _is_explicit_true(supplier.get("authorization")):
        return True
    return False


def validate_supplier_qpl(rfq: Dict[str, Any], supplier: Dict[str, Any]) -> Dict[str, Any]:
    """Validate supplier eligibility for QPL/QML and source approval requirements."""
    reasons: List[str] = []
    risk_flags: List[str] = []

    qpl_required = _requires_qpl_or_qml(rfq)
    coqc_required = _requires_coqc(rfq)
    critical_item = _is_critical_application_item(rfq)

    status = STATUS_PASS

    if critical_item:
        risk_flags.append("CRITICAL_APPLICATION_ITEM")

    if qpl_required:
        role = _normalize_role(supplier.get("role"))
        authorized_distributor = _supplier_is_authorized_distributor(supplier)
        if role == "manufacturer":
            pass
        elif role in {"authorized_distributor", "authorized_distributor_only"}:
            pass
        elif role == "distributor" and authorized_distributor:
            pass
        elif role == "reseller" or (role == "distributor" and not authorized_distributor):
            status = STATUS_FAIL
            reasons.append("QPL/QML item requires manufacturer authorization")
            if role == "reseller":
                reasons.append("Supplier role is reseller")
            else:
                reasons.append("Distributor authorization is not documented")
        else:
            status = STATUS_CONDITIONAL
            reasons.append("QPL/QML item requires manufacturer or authorized distributor")
            reasons.append("Supplier authorization not documented")

    if coqc_required:
        traceability = _is_explicit_true(supplier.get("manufacturer_traceability"))
        if not traceability:
            status = STATUS_FAIL
            reasons.append("COQC required but manufacturer traceability is not documented")

    eligible = status == STATUS_PASS

    return {
        "eligible": eligible,
        "status": status,
        "reasons": reasons,
        "risk_flags": risk_flags,
    }
