"""OpenAI-compatible chat adapter (ADR-008).

Three .env values select the provider: LLM_BASE_URL, LLM_API_KEY,
LLM_MODEL. Works with OpenAI, OpenRouter, Groq, Ollama, and vLLM.
"""

import json
import os
import time
import urllib.request


class OpenAICompatibleLLM:
    def __init__(self):
        self.base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.api_key = os.environ.get("LLM_API_KEY")
        self.model = os.environ.get("LLM_MODEL")
        if not self.api_key or not self.model:
            raise RuntimeError("LLM_API_KEY / LLM_MODEL are not set")
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        # One DNS hiccup must not cost a beat — or, in parallel mode,
        # the whole session. Retry transient network failures briefly.
        last_err = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read())
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last_err = e
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        else:
            raise last_err
        usage = data.get("usage") or {}
        self.calls += 1
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        return data["choices"][0]["message"]["content"]
