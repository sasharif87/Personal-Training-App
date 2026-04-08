# backend/llm/ollama_client.py
"""
Backward-compatible re-export of the canonical OllamaClient.

The unified client now lives in backend.orchestration.llm_client with
dual-host fallback, temperature control, and markdown-stripping safety.

CoachingLLMClient is retained as a thin alias for any code that still
references it by name.
"""

from backend.orchestration.llm_client import OllamaClient

# Alias for backward compatibility
CoachingLLMClient = OllamaClient

# Singleton — lazy-initialized from env vars
llm_client = OllamaClient()
