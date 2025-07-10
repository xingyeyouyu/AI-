"""llm_adapter.py - 多大模型回退适配器 (与 tts2 同步)"""
from __future__ import annotations

import logging
import os
import json
import httpx
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """统一的 Provider 异常"""


class BaseProvider:
    name: str = "base"

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int = 150,
        temperature: float = 0.8,
    ) -> str:  # noqa: D401
        raise ProviderError("not implemented")


class DeepSeekProvider(BaseProvider):
    name = "deepseek"

    def __init__(self, client, default_model: str, enabled: bool = True):
        super().__init__(enabled)
        self._client = client
        self._default_model = default_model

    def chat(self, messages: List[Dict[str, Any]], *, model: str | None = None, max_tokens: int = 150, temperature: float = 0.8) -> str:  # noqa: D401
        if not self.enabled:
            raise ProviderError("DeepSeekProvider disabled")
        resp = self._client.chat.completions.create(
            model=model or self._default_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip()


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        default_model: str = "gpt-3.5-turbo",
        proxy: str | None = None,
        enabled: bool = True,
    ):
        super().__init__(enabled)
        try:
            import openai  # noqa: PLC0414
        except ImportError as exc:
            raise ProviderError("openai sdk missing") from exc
        if not api_key:
            raise ProviderError("OPENAI_API_KEY missing")
        http_client = httpx.Client(proxies=proxy, timeout=60.0) if proxy else None
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, http_client=http_client) if http_client else openai.OpenAI(api_key=api_key, base_url=base_url)
        self._default_model = default_model
        self._proxy = proxy

    def chat(self, messages: List[Dict[str, Any]], *, model: str | None = None, max_tokens: int = 150, temperature: float = 0.8) -> str:  # noqa: D401
        if not self.enabled:
            raise ProviderError("OpenAIProvider disabled")
        resp = self._client.chat.completions.create(
            model=model or self._default_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip()


class DummyProvider(BaseProvider):
    def __init__(self, name: str):
        super().__init__(enabled=False)
        self.name = name

    def chat(self, *args, **kwargs):  # noqa: D401, ANN002
        raise ProviderError(f"Provider {self.name} not implemented")


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, api_key: str, default_model: str = "gemini-pro", proxy: str | None = None, enabled: bool = True):
        super().__init__(enabled)
        try:
            import google.generativeai as genai  # type: ignore
        except ImportError as exc:
            raise ProviderError("google-generativeai 未安装，请 pip install google-generativeai") from exc

        if not api_key:
            raise ProviderError("GEMINI_API_KEY missing")

        if proxy:
            os.environ["HTTPS_PROXY"] = proxy
            os.environ["HTTP_PROXY"] = proxy
        genai.configure(api_key=api_key)
        self._genai = genai
        self._default_model = default_model
        self._proxy = proxy

    def _merge_messages(self, messages):
        parts = [f"{m['role']}: {m['content']}" for m in messages]
        return "\n".join(parts)

    def chat(self, messages, *, model=None, max_tokens=150, temperature=0.8):  # noqa: D401, ANN002
        if not self.enabled:
            raise ProviderError("GeminiProvider disabled")

        prompt = self._merge_messages(messages)
        mdl = model or self._default_model
        model_obj = self._genai.GenerativeModel(mdl)
        resp = model_obj.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        return resp.text.strip()


class ClaudeProvider(BaseProvider):
    name = "claude"

    def __init__(self, api_key: str, default_model: str = "claude-3-sonnet-20240229", proxy: str | None = None, enabled: bool = True):
        super().__init__(enabled)
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise ProviderError("anthropic SDK 未安装，请 pip install anthropic") from exc

        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY missing")

        self._proxy = proxy
        self._client = anthropic.Anthropic(api_key=api_key, proxies={"http": proxy, "https": proxy}) if proxy else anthropic.Anthropic(api_key=api_key)
        self._default_model = default_model

    def chat(self, messages: List[Dict[str, Any]], *, model=None, max_tokens=150, temperature=0.8):
        if not self.enabled:
            raise ProviderError("ClaudeProvider disabled")

        claude_msgs = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages]

        resp = self._client.messages.create(
            model=model or self._default_model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=claude_msgs,
        )
        return resp.content[-1].text.strip()  # type: ignore


class LocalProvider(BaseProvider):
    name = "local"

    def __init__(self, endpoint: str, default_model: str = "local-model", proxy: str | None = None, enabled: bool = True, timeout: float = 60.0):
        super().__init__(enabled)
        self._endpoint = endpoint.rstrip("/") + "/v1/chat/completions"
        self._default_model = default_model
        self._timeout = timeout
        self._proxy = proxy

    def chat(self, messages: List[Dict[str, Any]], *, model=None, max_tokens=150, temperature=0.8):
        if not self.enabled:
            raise ProviderError("LocalProvider disabled")

        payload = {
            "model": model or self._default_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            r = httpx.post(self._endpoint, json=payload, timeout=self._timeout, proxies=self._proxy) if self._proxy else httpx.post(self._endpoint, json=payload, timeout=self._timeout)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"LocalProvider HTTP error: {exc}") from exc


class LLMRouter:
    def __init__(self, cfg, *, deepseek_client=None):
        default_order = ["deepseek", "openai", "claude", "gemini", "local"]
        order_raw = cfg.get("DEFAULT", "llm.order", fallback=",".join(default_order))
        self._order = [n.strip() for n in order_raw.split(",") if n.strip()] if order_raw else default_order
        self._providers: List[BaseProvider] = []
        for name in self._order:
            enabled = cfg.getboolean("DEFAULT", f"{name}.enable", fallback=True)
            if name == "deepseek":
                if deepseek_client is None:
                    logger.warning("No deepseek client; skip provider")
                    continue
                self._providers.append(
                    DeepSeekProvider(deepseek_client, cfg.get("DEFAULT", "model.name", fallback="deepseek-chat"), enabled)
                )
            elif name == "openai":
                try:
                    api_key = cfg.get("DEFAULT", "openai.api_key", fallback=os.getenv("OPENAI_API_KEY", "")).strip()
                    base_url = cfg.get("DEFAULT", "openai.base_url", fallback="https://api.openai.com/v1").strip()
                    model = cfg.get("DEFAULT", "openai.model", fallback="gpt-3.5-turbo").strip()
                    proxy = cfg.get("DEFAULT", "openai.proxy", fallback=cfg.get("NETWORK", "proxy", fallback="")).strip() or None
                    self._providers.append(OpenAIProvider(api_key, base_url, model, proxy, enabled))
                except ProviderError as exc:
                    logger.warning("OpenAI provider init failed: %s", exc)
            elif name == "gemini":
                try:
                    api_key = cfg.get("DEFAULT", "gemini.api_key", fallback=os.getenv("GEMINI_API_KEY", "")).strip()
                    model = cfg.get("DEFAULT", "gemini.model", fallback="gemini-pro").strip()
                    proxy = cfg.get("DEFAULT", "gemini.proxy", fallback=cfg.get("NETWORK", "proxy", fallback="")).strip() or None
                    self._providers.append(GeminiProvider(api_key, model, proxy, enabled))
                except ProviderError as exc:
                    logger.warning("GeminiProvider init failed: %s", exc)
            elif name == "claude":
                try:
                    api_key = cfg.get("DEFAULT", "claude.api_key", fallback=os.getenv("ANTHROPIC_API_KEY", "")).strip()
                    model = cfg.get("DEFAULT", "claude.model", fallback="claude-3-sonnet-20240229").strip()
                    proxy = cfg.get("DEFAULT", "claude.proxy", fallback=cfg.get("NETWORK", "proxy", fallback="")).strip() or None
                    self._providers.append(ClaudeProvider(api_key, model, proxy, enabled))
                except ProviderError as exc:
                    logger.warning("初始化 ClaudeProvider 失败: %s", exc)
            elif name == "local":
                endpoint = cfg.get("DEFAULT", "local.endpoint", fallback="http://127.0.0.1:8000").strip()
                model = cfg.get("DEFAULT", "local.model", fallback="local-model").strip()
                proxy = cfg.get("DEFAULT", "local.proxy", fallback=cfg.get("NETWORK", "proxy", fallback="")).strip() or None
                self._providers.append(LocalProvider(endpoint, model, proxy, enabled))
            else:
                self._providers.append(DummyProvider(name))
        if not self._providers:
            raise RuntimeError("No LLM providers available")

    def chat(self, messages: List[Dict[str, Any]], *, model: str | None = None, max_tokens: int = 150, temperature: float = 0.8) -> str:  # noqa: D401
        last_exc: Exception | None = None
        for p in self._providers:
            if not p.enabled:
                continue
            try:
                return p.chat(messages, model=model, max_tokens=max_tokens, temperature=temperature)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Provider %s failed: %s", p.name, exc)
                last_exc = exc
        raise ProviderError(str(last_exc) if last_exc else "All providers failed") 