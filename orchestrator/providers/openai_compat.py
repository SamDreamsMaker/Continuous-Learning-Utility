"""OpenAI-compatible provider (LM Studio, OpenAI, Ollama, vLLM, etc.)."""

import time
import logging

import openai

from orchestrator.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class OpenAICompatProvider(LLMProvider):
    """
    Provider for any OpenAI-compatible API.

    Covers: LM Studio, OpenAI cloud, Ollama, vLLM, text-generation-inference.
    Uses stream=False for reliable tool calling across all backends.
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self._base_url = base_url
        self._api_key = api_key or "not-needed"
        self._model = model
        self.client = openai.OpenAI(
            base_url=base_url,
            api_key=self._api_key,
        )

    @property
    def provider_name(self) -> str:
        return "OpenAI-compatible"

    @property
    def model_name(self) -> str:
        return self._model

    def chat_completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        max_retries = 3

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=tools if tools else openai.NOT_GIVEN,
                    stream=False,
                    **kwargs,
                )

                message = response.choices[0].message
                tool_calls = None
                if message.tool_calls:
                    tool_calls = [
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                        for tc in message.tool_calls
                    ]

                return LLMResponse(
                    content=message.content,
                    tool_calls=tool_calls,
                    prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                    completion_tokens=response.usage.completion_tokens if response.usage else 0,
                )

            except openai.APIConnectionError as e:
                logger.warning(
                    "Connection failed (attempt %d/%d): %s",
                    attempt + 1, max_retries, e,
                )
                if attempt == max_retries - 1:
                    raise ConnectionError(
                        f"API unreachable after {max_retries} attempts: {e}"
                    ) from e
                time.sleep(2 ** attempt)

            except openai.APIStatusError as e:
                # Context overflow → fail immediately (no retry)
                msg = str(e).lower()
                if e.status_code == 400 and (
                    "n_keep" in msg or "n_ctx" in msg
                    or "context_length_exceeded" in msg
                    or "maximum context length" in msg
                ):
                    from orchestrator.exceptions import ContextOverflowError
                    raise ContextOverflowError(
                        f"Prompt exceeds model context window: {e}"
                    ) from e

                logger.warning(
                    "API error (attempt %d/%d): %s",
                    attempt + 1, max_retries, e,
                )
                if attempt == max_retries - 1:
                    raise ConnectionError(
                        f"API error after {max_retries} attempts: {e}"
                    ) from e
                time.sleep(2 ** attempt)

    def test_connection(self) -> dict:
        try:
            models = self.client.models.list()
            available = [m.id for m in models.data]
            logger.info("Available models: %s", available)
            return {"ok": True, "models": available}
        except Exception as e:
            logger.error("Connection test failed: %s", e)
            return {"ok": False, "error": str(e)}

    def list_models(self) -> list[str]:
        result = self.test_connection()
        return result.get("models", []) if result.get("ok") else []
