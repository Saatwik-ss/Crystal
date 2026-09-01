import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from unittest.mock import patch, MagicMock
from services.provider_router import (
    is_gemini_key,
    detect_provider,
    resolve_provider_model,
    create_provider_client,
    get_provider_info,
    PROVIDERS,
)
from services.llm_config import get_groq_client, supports_tools


def test_is_gemini_key():
    assert is_gemini_key("AIzaSyB1234567890abcdef") is True
    assert is_gemini_key("AQ.1234567890abcdef") is True
    assert is_gemini_key("  AQ.TestKey  ") is True
    assert is_gemini_key("gsk_1234567890abcdef") is False
    assert is_gemini_key("") is False
    assert is_gemini_key(None) is False


def test_detect_provider():
    assert detect_provider(api_key="AIzaSy123") == "gemini"
    assert detect_provider(api_key="AQ.123") == "gemini"
    assert detect_provider(api_key="gsk_123") == "groq"
    assert detect_provider(api_key="random", model="gemini-2.5-flash") == "gemini"
    assert detect_provider(api_key="random", model="llama-3.3-70b-versatile") == "groq"
    with patch.dict("os.environ", {}, clear=True):
        assert detect_provider() == "groq"


def test_resolve_provider_model():
    # Gemini
    assert resolve_provider_model("gemini", None) == "gemini-2.5-flash"
    assert resolve_provider_model("gemini", "") == "gemini-2.5-flash"
    assert resolve_provider_model("gemini", "llama-3.3-70b-versatile") == "gemini-2.5-flash"
    assert resolve_provider_model("gemini", "gemini-1.5-pro") == "gemini-1.5-pro"

    # Groq
    assert resolve_provider_model("groq", None) == "llama-3.3-70b-versatile"
    assert resolve_provider_model("groq", "llama-3.1-8b-instant") == "llama-3.1-8b-instant"
    assert resolve_provider_model("groq", "gemini-2.5-flash") == "llama-3.3-70b-versatile"


def test_get_provider_info():
    groq_info = get_provider_info("groq")
    assert "api.groq.com" in groq_info["models_url"]
    assert groq_info["base_url"] == "https://api.groq.com/openai/v1"

    gemini_info = get_provider_info("gemini")
    assert "generativelanguage.googleapis.com" in gemini_info["models_url"]
    assert "generativelanguage.googleapis.com" in gemini_info["base_url"]


def test_create_gemini_client():
    client, model, initialized = create_provider_client("gemini", "AIzaSyFakeKey123")
    assert initialized is True
    assert model == "gemini-2.5-flash"
    assert "generativelanguage.googleapis.com" in str(client.base_url)
    assert hasattr(client, "chat")
    assert hasattr(client.chat, "completions")


def test_create_gemini_client_fallback_without_openai():
    # Simulate environment where openai package is not installed
    with patch.dict("sys.modules", {"openai": None}):
        client, model, initialized = create_provider_client("gemini", "AIzaSyFakeKey123")
        assert initialized is True
        assert model == "gemini-2.5-flash"
        assert "generativelanguage.googleapis.com" in str(client.base_url)
        assert hasattr(client, "chat")
        assert hasattr(client.chat, "completions")


def test_get_groq_client_delegation():
    # Test that passing a Gemini key delegates to Gemini
    client, model, initialized = get_groq_client(user_key="AIzaSyKey123")
    assert initialized is True
    assert model == "gemini-2.5-flash"
    assert "generativelanguage.googleapis.com" in str(client.base_url)

    # Test that passing a Groq key initializes Groq
    with patch("groq.Groq") as mock_groq:
        mock_groq.return_value = MagicMock()
        client, model, initialized = get_groq_client(user_key="gsk_real_or_mock_key")
        assert initialized is True
        assert model == "llama-3.3-70b-versatile"
        mock_groq.assert_called_once_with(api_key="gsk_real_or_mock_key")


def test_supports_tools_for_gemini():
    assert supports_tools("gemini-2.5-flash") is True
    assert supports_tools("gemini-1.5-pro") is True
    assert supports_tools("llama-3.3-70b-versatile") is True
    assert supports_tools("whisper-large-v3") is False


def test_api_models_endpoint_routes_to_gemini():
    import asyncio
    from main import app
    from httpx import AsyncClient

    captured_url = None

    async def mock_get(url, *args, **kwargs):
        nonlocal captured_url
        captured_url = url
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"id": "gemini-2.5-flash", "object": "model"},
                {"id": "gemini-1.5-pro", "object": "model"},
                {"id": "text-embedding-004", "object": "model"},
            ]
        }
        return mock_resp

    async def _run():
        with patch("httpx.AsyncClient.get", side_effect=mock_get):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.post("/api/models", json={"api_key": "AIzaSyTestKey"})
                assert resp.status_code == 200
                data = resp.json()
                assert "generativelanguage.googleapis.com" in captured_url
                model_ids = [m["id"] for m in data["data"]]
                assert "gemini-2.5-flash" in model_ids
                assert "gemini-1.5-pro" in model_ids
                # Non-chat models should be filtered out
                assert "text-embedding-004" not in model_ids

    asyncio.run(_run())


def test_api_models_endpoint_routes_to_groq():
    import asyncio
    from main import app
    from httpx import AsyncClient

    captured_url = None

    async def mock_get(url, *args, **kwargs):
        nonlocal captured_url
        captured_url = url
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"id": "llama-3.3-70b-versatile", "object": "model"}]
        }
        return mock_resp

    async def _run():
        with patch("httpx.AsyncClient.get", side_effect=mock_get):
            async with AsyncClient(app=app, base_url="http://test") as client:
                resp = await client.post("/api/models", json={"api_key": "gsk_test_key"})
                assert resp.status_code == 200
                assert "api.groq.com" in captured_url

    asyncio.run(_run())

