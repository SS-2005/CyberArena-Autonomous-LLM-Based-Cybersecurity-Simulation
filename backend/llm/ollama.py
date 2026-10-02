import json
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Iterator
import httpx

from backend.llm.base import LLMProvider
from backend.schemas.llm import LLMGenerationResponse, LLMHealthResponse
from backend.utils.logger import logger


class OllamaProvider(LLMProvider):
    """
    Local Ollama LLM provider implementation for CyberArena.
    Handles communication with local Ollama daemon via its HTTP API.
    Designed for local, offline, CPU-friendly inference.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:11434", default_timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.default_timeout = default_timeout

    def list_models(self) -> List[str]:
        """Query local Ollama for all installed model names/tags."""
        url = f"{self.base_url}/api/tags"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    models = data.get("models", [])
                    return [m.get("name") or m.get("model") for m in models if m.get("name") or m.get("model")]
                logger.warning(f"Ollama list_models returned status {res.status_code}: {res.text}")
                return []
        except Exception as e:
            logger.error(f"Failed to connect to Ollama at {self.base_url}: {e}")
            return []

    def list_models_detailed(self) -> Dict[str, Dict[str, Any]]:
        """Query local Ollama for all installed models with file size, capabilities, and parameter details."""
        url = f"{self.base_url}/api/tags"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    models = data.get("models", [])
                    out: Dict[str, Dict[str, Any]] = {}
                    for m in models:
                        name = m.get("name") or m.get("model")
                        if not name:
                            continue
                        size_b = m.get("size", 0)
                        size_str = (
                            f"{round(size_b / (1024 * 1024 * 1024), 2)} GB"
                            if size_b >= 1024**3
                            else f"{round(size_b / (1024 * 1024), 1)} MB"
                        )
                        caps = m.get("capabilities", [])
                        out[name] = {
                            "size_bytes": size_b,
                            "size_formatted": size_str,
                            "capabilities": caps,
                            "details": m.get("details", {}),
                            "thinking_supported": "thinking" in caps,
                        }
                    return out
                return {}
        except Exception as e:
            logger.debug(f"Failed to fetch detailed models from Ollama: {e}")
            return {}

    def generate(
        self,
        model_name: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_format: bool = False,
        temperature: float = 0.2,
        timeout: Optional[int] = None,
        think: Optional[bool] = None,
        num_ctx: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMGenerationResponse:
        """
        Generate completion from local Ollama model.
        """
        start_time = time.time()
        eff_timeout = float(timeout or self.default_timeout)
        options: Dict[str, Any] = {"temperature": temperature}
        if think is not None:
            options["think"] = think
        if num_ctx is not None:
            options["num_ctx"] = num_ctx
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        payload: Dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": options,
            "keep_alive": "60m",
        }
        if system_prompt:
            payload["system"] = system_prompt
        if json_format:
            payload["format"] = "json"

        url = f"{self.base_url}/api/generate"
        try:
            with httpx.Client(timeout=eff_timeout) as client:
                res = client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    return LLMGenerationResponse(
                        text=data.get("response", ""),
                        duration=round(time.time() - start_time, 3),
                        model_name=model_name,
                        tokens_generated=data.get("eval_count", 0),
                    )
                raise RuntimeError(f"Ollama generation failed with status {res.status_code}: {res.text}")
        except (httpx.TimeoutException, TimeoutError) as e:
            raise TimeoutError(f"Ollama generation timed out after {eff_timeout}s: {e}")
        except Exception as e:
            if isinstance(e, (TimeoutError, RuntimeError)):
                raise
            raise RuntimeError(f"Ollama generation request error: {e}")

    def health_check(self) -> LLMHealthResponse:
        """Check Ollama connectivity and installed models."""
        url = f"{self.base_url}/api/tags"
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    models = [m.get("name") or m.get("model") for m in data.get("models", [])]
                    return LLMHealthResponse(
                        status="healthy",
                        provider="ollama",
                        base_url=self.base_url,
                        installed_models=models,
                        message=f"Ollama operational. {len(models)} local models detected.",
                        timestamp=now_iso,
                    )
                return LLMHealthResponse(
                    status="degraded",
                    provider="ollama",
                    base_url=self.base_url,
                    installed_models=[],
                    message=f"Ollama responded with HTTP {res.status_code}",
                    timestamp=now_iso,
                )
        except Exception as e:
            return LLMHealthResponse(
                status="unreachable",
                provider="ollama",
                base_url=self.base_url,
                installed_models=[],
                message=f"Cannot reach Ollama at {self.base_url}: {e}",
                timestamp=now_iso,
            )

    def generate_stream(
        self,
        model_name: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_format: bool = False,
        temperature: float = 0.2,
        timeout: Optional[int] = None,
        think: Optional[bool] = None,
        num_ctx: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Stream completion chunks from local Ollama model in real-time.
        Yields dicts with type ('thinking' | 'response'), chunk text, done flag, duration.
        """
        url = f"{self.base_url}/api/generate"
        eff_timeout = float(timeout or self.default_timeout)

        options: Dict[str, Any] = {
            "temperature": temperature,
            "repeat_penalty": 1.1,
            "num_thread": 8,
        }
        if num_ctx:
            options["num_ctx"] = num_ctx
        if max_tokens:
            options["num_predict"] = max_tokens

        payload: Dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "stream": True,
            "keep_alive": "60m",
            "options": options,
        }

        if think is not None:
            payload["think"] = think

        if system_prompt:
            payload["system"] = system_prompt

        if json_format:
            payload["format"] = "json"

        start_time = time.time()
        client_timeout = httpx.Timeout(timeout=eff_timeout, connect=15.0, read=120.0, write=30.0)
        try:
            with httpx.Client(timeout=client_timeout) as client:
                with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        err_text = response.read().decode(errors="replace")
                        raise RuntimeError(f"Ollama streaming failed ({response.status_code}): {err_text}")
                    for line in response.iter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        chunk_text = data.get("response", "")
                        thinking_text = data.get("thinking", "")
                        done = data.get("done", False)

                        # Yield thinking token if present
                        if thinking_text:
                            yield {
                                "chunk": thinking_text,
                                "type": "thinking",
                                "done": False,
                                "eval_count": data.get("eval_count"),
                                "total_duration": data.get("total_duration"),
                                "duration": round(time.time() - start_time, 3),
                            }
                        # Yield response token if present
                        if chunk_text:
                            yield {
                                "chunk": chunk_text,
                                "type": "response",
                                "done": done,
                                "eval_count": data.get("eval_count"),
                                "total_duration": data.get("total_duration"),
                                "duration": round(time.time() - start_time, 3),
                            }
                        # If done and neither had tokens, yield done indicator
                        if done and not chunk_text and not thinking_text:
                            yield {
                                "chunk": "",
                                "type": "response",
                                "done": True,
                                "eval_count": data.get("eval_count"),
                                "total_duration": data.get("total_duration"),
                                "duration": round(time.time() - start_time, 3),
                            }
                        if done:
                            break
        except httpx.TimeoutException as e:
            err_msg = f"Ollama streaming timed out after {eff_timeout}s: {e}"
            logger.error(err_msg)
            raise TimeoutError(err_msg) from e
        except Exception as e:
            logger.error(f"Error during Ollama streaming: {e}")
            raise

