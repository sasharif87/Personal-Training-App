# backend/llm/ollama_client.py
"""
Ollama Client Interface.
Handles dual-host fallback logic between primary (gaming rig) and fallback (TrueNAS).
Enforces JSON-only responses explicitly for downstream piping.
"""

import os
import json
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class CoachingLLMClient:
    def __init__(self):
        # Allow multi-host deployment (gaming rig primary, truenas fallback)
        self.primary_url = os.getenv("OLLAMA_PRIMARY_URL", "http://192.168.50.250:11434").rstrip("/")
        self.fallback_url = os.getenv("OLLAMA_FALLBACK_URL", "http://192.168.50.46:11434").rstrip("/")
        
        self.heavy_model = os.getenv("OLLAMA_HEAVY_MODEL", "qwen2.5:72b")
        self.fast_model = os.getenv("OLLAMA_FAST_MODEL", "llama3.1:8b")
        
        # Test routing immediately on startup
        self._active_url = self._determine_primary_route()

    def _determine_primary_route(self) -> str:
        """Ping the primary endpoint, drop gracefully to fallback if offline."""
        if self._ping(self.primary_url):
            logger.info(f"Ollama connected: Primary route active [{self.primary_url}]")
            return self.primary_url
            
        elif self._ping(self.fallback_url):
            logger.info(f"Ollama fallback active: Primary unreachable. Routing to [{self.fallback_url}]")
            return self.fallback_url
            
        logger.warning("No Ollama instances reachable. LLM pipeline operations will fail.")
        return self.primary_url  # default

    def _ping(self, url: str) -> bool:
        try:
            req = urllib.request.Request(f"{url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as _:
                return True
        except Exception:
            return False

    def generate_json(self, prompt: str, use_heavy: bool = False, timeout: int = 120) -> Dict[str, Any]:
        """
        Sends the prompt to Ollama, enforcing JSON mode.
        Returns parsed JSON dict. Raises RuntimeError on total failure.
        """
        model = self.heavy_model if use_heavy else self.fast_model
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",    # Enforce native constraint mapping for JSON schemas
            "options": {
                "temperature": 0.2 if use_heavy else 0.4
            }
        }
        
        # Try active route first
        try:
            return self._send_request(self._active_url, payload, timeout)
            
        except Exception as e:
            logger.error(f"Failed to generate from active endpoint {self._active_url}: {e}")
            
            # If we failed and there's a fallback available that isn't the active one, try it
            other_url = self.fallback_url if self._active_url == self.primary_url else self.primary_url
            if self._ping(other_url):
                logger.info(f"Switching active Ollama route to {other_url}")
                self._active_url = other_url
                try:
                    return self._send_request(self._active_url, payload, timeout)
                except Exception as e:
                    logger.error(f"Failed to generate from fallback endpoint {self._active_url}: {e}")
                    raise RuntimeError("All Ollama generation routes failed.") from e
            
            raise RuntimeError(f"Ollama generation failed and no fallback available. ({e})")

    def _send_request(self, host: str, payload: dict, timeout: int) -> Dict[str, Any]:
        """Base http request and JSON unwrapper."""
        req = urllib.request.Request(
            f"{host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
            raw_response = result.get("response", "{}")
            
            # Even with format="json", safety check if model hallucinates markdown
            clean_text = raw_response.strip("```json").strip("```").strip()
            
            if not clean_text:
                return {}
                
            return json.loads(clean_text)

# Singleton instantiation for the app
llm_client = CoachingLLMClient()
