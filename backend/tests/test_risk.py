# backend/tests/test_risk.py
"""任务 32：风险评估器单测。"""
from app.tools.risk import needs_confirmation, needs_approval


def test_high_risk_needs_confirmation():
    """high：需即时确认（interrupt），不进审批中心。"""
    assert needs_confirmation("high") is True
    assert needs_approval("high") is False


def test_critical_risk_needs_approval():
    """critical：需进审批中心正式审批。"""
    assert needs_confirmation("critical") is False
    assert needs_approval("critical") is True


def test_low_medium_skips():
    """low/medium：直接执行。"""
    assert needs_confirmation("low") is False
    assert needs_approval("low") is False
    assert needs_confirmation("medium") is False
    assert needs_approval("medium") is False