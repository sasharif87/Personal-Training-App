"""
engine.py — Ollama client with model switching.

Different tasks need different models:
  - "reason"  → deep analysis, architecture parsing, rule generation
  - "code"    → file generation, fix application
  - "quick"   → fast classification, yes/no decisions, small edits

The engine auto-detects available models and picks the best one per role,
or you can pin models explicitly.
"""

import json
import os
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime

# ---------------------------------------------------------------------------
# Model role defaults — ordered by preference (first available wins)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Model role defaults — ordered by preference (first available wins)
# ---------------------------------------------------------------------------
MODEL_PREFERENCES = {
    "reason": [
        # TrueNAS pool — Quadro RTX 5000 16GB
        "deepseek-r1:32b", "deepseek-r1:14b", "deepseek-r1:8b",
        "qwen2.5:14b",             # on TrueNAS: best available reason model
        "qwen2.5:32b",
        "qwen3:32b", "qwen3:14b",
        "llama3.1:70b", "llama3.1:8b",
        "gemma2:27b", "gemma2:9b",
        "mistral-small:latest",    # on TrueNAS: 23.6B, strong reasoner fallback
        "deepseek-coder-v2:16b",   # on TrueNAS: fallback — can reason okay
    ],
    "code": [
        # Large models — gaming rig (7800XT 16GB, 9950X3D)
        "qwen2.5:72b", "qwen2.5-coder:32b",
        # Mid-range
        "qwen2.5-coder:14b", "qwen2.5-coder:7b",
        "deepseek-coder-v2:16b",  # older architecture — fallback if no qwen2.5-coder available
        "codellama:34b", "codellama:13b",
        "deepseek-r1:14b",  # fallback — can code okay
        "llama3.1:8b",
    ],
    "quick": [
        # TrueNAS pool — ordered by speed vs capability
        "qwen2.5-coder:7b",        # ideal: fast + code-aware (pull if available)
        "qwen2.5-coder:14b",       # on TrueNAS: best available quick model
        "qwen2.5:14b", "qwen2.5:7b",
        "gemma2:9b", "llama3.1:8b", "llama3.2:3b",
        "phi3:mini",
        "deepseek-coder-v2:16b",   # fallback
        "mistral:7b-instruct",
    ],
}

# Context windows and temperature defaults per role
CTX_DEFAULTS = {
    "reason": 16384,
    "code": 32768,
    "quick": 4096,
}

TEMP_DEFAULTS = {
    "reason": 0.15,
    "code": 0.1,
    "quick": 0.05,
}


# ---------------------------------------------------------------------------
# Engine — Ollama client with automatic model selection per task role
# ---------------------------------------------------------------------------
class Engine:

    def __init__(self, url="http://192.168.50.46:11434", models=None, code_url=None):
        """
        Args:
            url:      Ollama URL for quick + reason roles.
                      Default: TrueNAS (i5-7600 + Quadro RTX 5000 16GB)
                        quick  -> qwen2.5-coder:7b
                        reason -> deepseek-r1:14b
            code_url: Ollama URL for code role. Falls back to `url` if omitted.
                      Default: gaming rig (9950X3D + 7800XT 16GB)
                        code   -> qwen2.5:72b
            models:   Optional dict pinning roles to specific model names,
                      e.g. {"reason": "deepseek-r1:14b", "code": "qwen2.5:72b"}
        """
        self.url = url.rstrip("/")
        self.code_url = (code_url or url).rstrip("/")
        self.pinned = models or {}
        self._available = None        # models on url (quick/reason host)
        self._available_code = None   # models on code_url
        self._resolved = {}           # role -> model name

    # ── Connection & model discovery ─────────────────────────────────────────

    def test(self):
        """Test both hosts. Returns (ok, available_models, message) based on primary host."""
        ok, models, msg = self._probe(self.url)
        if ok:
            self._available = models
        # Probe code host separately (may differ from primary)
        if self.code_url != self.url:
            code_ok, code_models, _ = self._probe(self.code_url)
            if code_ok:
                self._available_code = code_models
        else:
            self._available_code = self._available
        if ok:
            self._resolve_models()
        return ok, models, msg

    def _probe(self, url):
        """Query /api/tags on a host. Returns (ok, model_list, message)."""
        try:
            req = urllib.request.Request(f"{url}/api/tags")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m["name"] for m in data.get("models", [])]
                return True, models, f"Connected ({url}) — {len(models)} model(s)"
        except Exception as e:
            return False, [], f"Cannot reach {url}: {e}"

    def _resolve_models(self):
        """Pick the best available model for each role.

        Routing:
          code  -> self._available_code (gaming rig pool)
          quick -> self._available       (TrueNAS pool)
          reason-> self._available       (TrueNAS pool)
        """
        if self._available is None:
            self.test()
            if self._available is None:
                return

        for role in ("reason", "code", "quick"):
            # Check pinned first
            if role in self.pinned:
                self._resolved[role] = self.pinned[role]
                continue

            # Route code role to the code host pool; others use the primary pool
            pool = (self._available_code or self._available) if role == "code" else self._available
            if not pool:
                pool = self._available or []

            # Walk preference list, pick first available in the right pool
            for pref in MODEL_PREFERENCES[role]:
                if pref in pool:
                    self._resolved[role] = pref
                    break
                # Partial match — only when pref has no size tag (e.g. "deepseek-coder-v2"
                # matches "deepseek-coder-v2:16b").  Never let a sized preference like
                # "qwen2.5-coder:7b" silently resolve to a larger variant like :32b.
                pref_base, pref_size = (pref.split(":", 1) + [""])[:2]
                if not pref_size:
                    for avail in pool:
                        if pref_base in avail:
                            self._resolved[role] = avail
                            break
                if role in self._resolved:
                    break

            # Ultimate fallback — use whatever's available in that pool
            if role not in self._resolved and pool:
                self._resolved[role] = pool[0]

    def model_for(self, role):
        """Get the resolved model name for a role."""
        if not self._resolved:
            self._resolve_models()
        return self._resolved.get(role, self.pinned.get("code", "llama3.1:8b"))

    def print_model_map(self):
        """Print which model is assigned to which role and which host."""
        if not self._resolved:
            self._resolve_models()
        dual = self.code_url != self.url
        print(f"\n  Model assignments:")
        for role in ("reason", "code", "quick"):
            model = self._resolved.get(role, "?")
            pinned = " (pinned)" if role in self.pinned else " (auto)"
            host = self.code_url if (dual and role == "code") else self.url
            host_label = f"  [{host}]" if dual else ""
            print(f"    {role:<8} -> {model}{pinned}{host_label}")
        print()

    # ── Generation ───────────────────────────────────────────────────────────

    def generate(self, prompt, *, role="code", temperature=None, num_ctx=None,
                 timeout=1800):
        """Send prompt to Ollama. Model + host selected by role."""
        model = self.model_for(role)
        host = self.code_url if role == "code" else self.url
        data = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None else TEMP_DEFAULTS.get(role, 0.1),
                "num_ctx": num_ctx or CTX_DEFAULTS.get(role, 16384),
            },
        }
        req = urllib.request.Request(
            f"{host}/api/generate",
            json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("response", "").strip()

    def chat(self, messages, *, role="code", temperature=None, num_ctx=None,
             timeout=1800):
        """Send chat messages to Ollama. Model selected by role."""
        model = self.model_for(role)
        data = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None else TEMP_DEFAULTS.get(role, 0.1),
                "num_ctx": num_ctx or CTX_DEFAULTS.get(role, 16384),
            },
        }
        host = self.code_url if role == "code" else self.url
        req = urllib.request.Request(
            f"{host}/api/chat",
            json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("message", {}).get("content", "").strip()


# ---------------------------------------------------------------------------
# Utilities used everywhere
# ---------------------------------------------------------------------------
def strip_fences(text):
    """Remove markdown code fences."""
    text = re.sub(r"^```[\w]*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text


def extract_json(text):
    """Extract JSON from model output that may have wrapping text."""
    text = strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in [r'\{[\s\S]*\}', r'\[[\s\S]*\]']:
        m = re.search(pattern, text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                continue
    return None


def read_file(path, max_chars=80_000):
    """Read file, return (content, error)."""
    try:
        if os.path.getsize(path) > max_chars:
            return None, f"too large ({os.path.getsize(path):,} chars)"
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except UnicodeDecodeError:
        return None, "binary"
    except Exception as e:
        return None, str(e)


def fmt_time(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h: return f"{h}h {m}m {s}s"
    if m: return f"{m}m {s}s"
    return f"{s}s"


def ts():
    return datetime.now().strftime("%H:%M:%S")


def log(msg):
    print(f"[{ts()}] {msg}")


def timed_input(prompt, timeout=0, default="y"):
    """Prompt for input. If timeout > 0 and no response arrives, returns default."""
    if timeout <= 0:
        try:
            return input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ""

    print(prompt, end=" ", flush=True)
    result = [None]

    def _read():
        try:
            result[0] = sys.stdin.readline().strip().lower()
        except Exception:
            result[0] = default

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout)
    if result[0] is None:
        print(f"(no response after {timeout}s — defaulting '{default}')")
        result[0] = default
    return result[0]