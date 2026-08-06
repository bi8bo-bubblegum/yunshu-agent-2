# backend/tests/test_factory.py
import pytest
from app.llm.factory import ModelFactory

def test_get_llm_by_key():
    assert ModelFactory.get_llm("default") is not None

def test_get_embedding():
    assert ModelFactory.get_embedding() is not None
