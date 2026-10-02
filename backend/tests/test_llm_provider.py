import pytest
from unittest.mock import MagicMock, patch
import httpx

from backend.llm.ollama import OllamaProvider
from backend.services.llm_service import LLMService
from backend.schemas.llm import ModelRegistryConfig, ModelConfig


def test_ollama_list_models_success():
    provider = OllamaProvider(base_url="http://127.0.0.1:11434")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {"name": "qwen3:4b", "size": 2497293931},
            {"model": "llama3.2:3b", "size": 2000000000},
        ]
    }

    with patch("httpx.Client.get", return_value=mock_response):
        models = provider.list_models()
        assert "qwen3:4b" in models
        assert "llama3.2:3b" in models


def test_ollama_list_models_unreachable():
    provider = OllamaProvider(base_url="http://invalid-host:11434")
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("Connection refused")):
        models = provider.list_models()
        assert models == []


def test_ollama_generate_success():
    provider = OllamaProvider(base_url="http://127.0.0.1:11434")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": '{"tool": "execute_command", "parameters": {"command": "hostname"}, "summary": "check hostname"}',
        "total_duration": 500000000,
        "eval_count": 25,
    }

    with patch("httpx.Client.request", return_value=mock_response):
        res = provider.generate(
            model_name="qwen3:4b",
            prompt="What is your next step?",
            json_format=True,
        )
        assert res.model_name == "qwen3:4b"
        assert "execute_command" in res.text
        assert res.tokens_generated == 25


def test_ollama_generate_timeout():
    provider = OllamaProvider(base_url="http://127.0.0.1:11434")
    with patch("httpx.Client.request", side_effect=httpx.ReadTimeout("timed out")):
        with pytest.raises(TimeoutError) as exc_info:
            provider.generate(model_name="qwen3:4b", prompt="ping", timeout=1)
        assert "timed out" in str(exc_info.value)


def test_ollama_health_check():
    provider = OllamaProvider(base_url="http://127.0.0.1:11434")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"models": [{"name": "qwen3:4b"}]}

    with patch("httpx.Client.get", return_value=mock_response):
        health = provider.health_check()
        assert health.status == "healthy"
        assert health.provider == "ollama"
        assert "qwen3:4b" in health.installed_models


def test_llm_service_model_distinctions():
    """Verify service distinguishes configured, installed, available, and unavailable models."""
    mock_provider = MagicMock()
    # Only qwen3:4b is physically installed in engine
    mock_provider.list_models.return_value = ["qwen3:4b", "unconfigured-extra:latest"]

    registry_config = ModelRegistryConfig(
        default_model="m1",
        models=[
            ModelConfig(model_id="m1", provider="ollama", model_name="qwen3:4b", enabled=True),
            ModelConfig(model_id="m2", provider="ollama", model_name="missing-model:latest", enabled=True),
            ModelConfig(model_id="m3", provider="ollama", model_name="qwen3:4b", enabled=False),
        ],
    )

    service = LLMService(provider=mock_provider, registry_config=registry_config)
    models = service.list_models()

    status_map = {m.model_id: m for m in models}

    # m1: configured=True, installed=True, available=True
    assert status_map["m1"].configured is True
    assert status_map["m1"].installed is True
    assert status_map["m1"].available is True

    # m2: configured=True, installed=False, available=False
    assert status_map["m2"].configured is True
    assert status_map["m2"].installed is False
    assert status_map["m2"].available is False

    # m3: configured=True, installed=True, but enabled=False -> available=False
    assert status_map["m3"].configured is True
    assert status_map["m3"].installed is True
    assert status_map["m3"].available is False

    # unconfigured-extra: configured=False, installed=True, available=False
    unconfigured = [m for m in models if not m.configured]
    assert len(unconfigured) == 1
    assert unconfigured[0].model_name == "unconfigured-extra:latest"
