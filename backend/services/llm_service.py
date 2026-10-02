from datetime import datetime, timezone
from typing import List, Optional, Dict
import time

from backend.configs.settings import load_model_registry, settings
from backend.llm.base import LLMProvider
from backend.llm.ollama import OllamaProvider
from backend.schemas.llm import (
    ModelConfig,
    ModelRegistryConfig,
    ModelStatus,
    LLMHealthResponse,
    LLMTestResponse,
    LLMGenerationResponse,
)
from backend.utils.logger import logger


class LLMService:
    """
    Core LLM management service for CyberArena.
    Reconciles configured models with physical provider installations.
    Manages provider instances without hardcoding model names.
    """

    def __init__(self, provider: Optional[LLMProvider] = None, registry_config: Optional[ModelRegistryConfig] = None):
        self.registry_config = registry_config or load_model_registry()
        self.provider = provider or OllamaProvider(
            base_url=settings.ollama_base_url,
            default_timeout=self.registry_config.default_timeout,
        )

    def refresh_registry(self) -> None:
        """Reload configuration from disk."""
        self.registry_config = load_model_registry()

    def get_health(self) -> LLMHealthResponse:
        """Query LLM provider health status."""
        return self.provider.health_check()

    def list_models(self) -> List[ModelStatus]:
        """
        List all models, distinguishing between:
        - configured models (declared in models.json)
        - installed models (present in the local inference engine)
        - available models (configured AND enabled AND installed)
        - unavailable models (configured but not installed or disabled)
        Enriched with size, capabilities, and thinking support.
        """
        installed = set(self.provider.list_models())
        details_map = {}
        if hasattr(self.provider, "list_models_detailed"):
            try:
                raw_det = self.provider.list_models_detailed()
                if isinstance(raw_det, dict):
                    details_map = raw_det
            except Exception as e:
                logger.debug(f"Could not fetch detailed model info: {e}")

        results: List[ModelStatus] = []
        configured_model_names = set()

        for m in self.registry_config.models:
            configured_model_names.add(m.model_name)
            is_installed = m.model_name in installed or any(m.model_name == k.split(":")[0] for k in installed)
            is_available = is_installed and m.enabled
            
            # Enrich size and thinking from provider if available
            det = details_map.get(m.model_name) or details_map.get(f"{m.model_name}:latest") or {}
            raw_size = m.size or (det.get("size_formatted") if isinstance(det, dict) else None)
            size_str = str(raw_size) if isinstance(raw_size, str) else None
            thinking_sup = bool(m.thinking_supported or (det.get("thinking_supported", False) if isinstance(det, dict) else False))
            
            details_dict = {"enabled_in_config": m.enabled}
            if m.temperature is not None:
                details_dict["temperature"] = m.temperature
            if m.num_ctx is not None:
                details_dict["num_ctx"] = m.num_ctx
            if m.max_tokens is not None:
                details_dict["max_tokens"] = m.max_tokens
            if isinstance(det, dict) and isinstance(det.get("details"), dict):
                details_dict.update(det["details"])

            results.append(
                ModelStatus(
                    model_id=m.model_id,
                    provider=m.provider,
                    model_name=m.model_name,
                    display_name=m.display_name or m.model_id,
                    configured=True,
                    installed=is_installed,
                    available=is_available,
                    size=size_str,
                    thinking_supported=thinking_sup,
                    think=m.think,
                    description=m.description,
                    details=details_dict,
                )
            )

        # Include unconfigured models that exist locally in the engine
        for inst_name in installed:
            if not isinstance(inst_name, str):
                continue
            if inst_name not in configured_model_names and not any(inst_name.startswith(c) for c in configured_model_names):
                det = details_map.get(inst_name, {}) if isinstance(details_map, dict) else {}
                raw_size = det.get("size_formatted") if isinstance(det, dict) else None
                results.append(
                    ModelStatus(
                        model_id=f"unconfigured-{inst_name.replace(':', '-')}",
                        provider="ollama",
                        model_name=inst_name,
                        display_name=inst_name,
                        configured=False,
                        installed=True,
                        available=False,
                        size=str(raw_size) if isinstance(raw_size, str) else None,
                        thinking_supported=bool(det.get("thinking_supported", False) if isinstance(det, dict) else False),
                        description="Installed locally in engine but not registered in models.json",
                    )
                )

        return results

    def resolve_model(self, model_id: Optional[str] = None) -> ModelConfig:
        """Resolve a model_id to its ModelConfig, falling back to default_model."""
        target_id = model_id or self.registry_config.default_model
        for m in self.registry_config.models:
            if m.model_id == target_id or m.model_name == target_id:
                return m
        raise ValueError(f"Model ID '{target_id}' is not configured in the model registry.")

    def test_model(self, model_id: Optional[str] = None, prompt: str = "ping") -> LLMTestResponse:
        """Execute a quick test prompt to verify local model inference."""
        model_cfg = self.resolve_model(model_id)
        start = time.time()
        eff_think = model_cfg.think
        gen_resp = self.provider.generate(
            model_name=model_cfg.model_name,
            prompt=prompt,
            temperature=model_cfg.temperature or 0.1,
            timeout=self.registry_config.default_timeout,
            think=eff_think,
            num_ctx=model_cfg.num_ctx,
            max_tokens=model_cfg.max_tokens or 256,
        )
        duration = round(time.time() - start, 3)
        return LLMTestResponse(
            model_id=model_cfg.model_id,
            model_name=model_cfg.model_name,
            response=gen_resp.text.strip(),
            duration=duration,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def generate(
        self,
        model_id: Optional[str],
        prompt: str,
        system_prompt: Optional[str] = None,
        json_format: bool = False,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        think: Optional[bool] = None,
        num_ctx: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMGenerationResponse:
        """Generate completion using configured model."""
        model_cfg = self.resolve_model(model_id)
        eff_timeout = timeout or self.registry_config.default_timeout
        eff_temp = temperature if temperature is not None else (model_cfg.temperature if model_cfg.temperature is not None else 0.2)
        eff_think = think if think is not None else model_cfg.think
        eff_ctx = num_ctx or model_cfg.num_ctx
        eff_max = max_tokens or model_cfg.max_tokens
        return self.provider.generate(
            model_name=model_cfg.model_name,
            prompt=prompt,
            system_prompt=system_prompt,
            json_format=json_format,
            temperature=eff_temp,
            timeout=eff_timeout,
            think=eff_think,
            num_ctx=eff_ctx,
            max_tokens=eff_max,
        )

    def generate_stream(
        self,
        model_id: Optional[str],
        prompt: str,
        system_prompt: Optional[str] = None,
        json_format: bool = False,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        think: Optional[bool] = None,
        num_ctx: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ):
        """Stream completion chunks using configured model."""
        model_cfg = self.resolve_model(model_id)
        eff_timeout = timeout or self.registry_config.default_timeout
        eff_temp = temperature if temperature is not None else (model_cfg.temperature if model_cfg.temperature is not None else 0.2)
        eff_think = think if think is not None else model_cfg.think
        eff_ctx = num_ctx or model_cfg.num_ctx
        eff_max = max_tokens or model_cfg.max_tokens
        return self.provider.generate_stream(
            model_name=model_cfg.model_name,
            prompt=prompt,
            system_prompt=system_prompt,
            json_format=json_format,
            temperature=eff_temp,
            timeout=eff_timeout,
            think=eff_think,
            num_ctx=eff_ctx,
            max_tokens=eff_max,
        )

    def test_model_stream(self, model_id: Optional[str] = None, prompt: str = "ping"):
        """Stream test prompt tokens for interactive model testing."""
        model_cfg = self.resolve_model(model_id)
        eff_timeout = self.registry_config.default_timeout
        system = "You are a concise cybersecurity assistant in CyberArena. Answer directly and concisely."
        eff_think = model_cfg.think
        return self.provider.generate_stream(
            model_name=model_cfg.model_name,
            prompt=prompt,
            system_prompt=system,
            temperature=model_cfg.temperature or 0.2,
            timeout=eff_timeout,
            think=eff_think,
            num_ctx=model_cfg.num_ctx,
            max_tokens=model_cfg.max_tokens or 256,
        )


