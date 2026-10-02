from abc import ABC, abstractmethod
from typing import List, Optional
from backend.schemas.llm import LLMGenerationResponse, LLMHealthResponse


class LLMProvider(ABC):
    """
    Abstract interface for Large Language Model Providers in CyberArena.
    Decouples the agent runtime and orchestrators from specific local inference engines.
    """

    @abstractmethod
    def list_models(self) -> List[str]:
        """List tags of all locally installed models in the provider engine."""
        pass

    @abstractmethod
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
        Generate completion from the specified model.
        When json_format=True, instructs provider to enforce valid JSON output schema.
        """
        pass

    @abstractmethod
    def health_check(self) -> LLMHealthResponse:
        """Check provider reachability and report engine status."""
        pass

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
    ):
        """
        Stream completion chunks from the specified model.
        Yields dicts with format: {"chunk": str, "done": bool, "eval_count": Optional[int], ...}
        Default implementation yields the single response from generate() for backward compatibility.
        """
        resp = self.generate(
            model_name=model_name,
            prompt=prompt,
            system_prompt=system_prompt,
            json_format=json_format,
            temperature=temperature,
            timeout=timeout,
            think=think,
            num_ctx=num_ctx,
            max_tokens=max_tokens,
        )
        yield {
            "chunk": resp.text,
            "done": True,
            "eval_count": resp.tokens_generated,
            "duration": resp.duration,
        }

