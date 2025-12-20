"""Unit-test stubs for QPL validation."""

from gov.supply_chain.qpl_validator import validate_supplier_qpl


def test_validate_supplier_qpl_stub() -> None:
    """Stub test to illustrate QPL validation entry point."""
    rfq = {"qpl_required": True}
    supplier = {"role": "manufacturer"}
    result = validate_supplier_qpl(rfq, supplier)
    assert isinstance(result, dict)
