"""llm_adapter.py
统一的大模型接口适配器。
支持 DeepSeek、OpenAI、Claude、Gemini、本地模型，并按配置顺序依次尝试。
目前仅 DeepSeek 与 OpenAI 提供完整实现，其余返回未实现异常。
"""
from __future__ import annotations

import logging
import os
import json
# For LocalProvider HTTP calls
import httpx
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """供 LLMProvider 抛出的统一异常，用于触发回退。"""


class BaseProvider:
    name: str = "base"

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    # pylint: disable=unused-argument
    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int = 150,
        temperature: float = 0.8,
    ) -> str:
        raise ProviderError("not implemented")


class DeepSeekProvider(BaseProvider):
    name = "deepseek"

    def __init__(
        self,
        client,  # 已初始化的 deepseek.OpenAI 实例
        default_model: str,
        enabled: bool = True,
    ):
        super().__init__(enabled)
        self._client = client
        self._default_model = default_model

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int = 150,
        temperature: float = 0.8,
    ) -> str:
        if not self.enabled:
            raise ProviderError("DeepSeekProvider disabled")
        response = self._client.chat.completions.create(
            model=model or self._default_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()


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
            raise ProviderError("openai python-sdk not installed") from exc

        if not api_key:
            raise ProviderError("OPENAI_API_KEY missing")

        http_client = httpx.Client(proxies=proxy, timeout=60.0) if proxy else None
        if http_client:
            self._client = openai.OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)
        else:
            self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self._proxy = proxy
        self._default_model = default_model

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int = 150,
        temperature: float = 0.8,
    ) -> str:
        if not self.enabled:
            raise ProviderError("OpenAIProvider disabled")
        response = self._client.chat.completions.create(
            model=model or self._default_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()


class GeminiProvider(BaseProvider):
    """Google Gemini (generative-ai) 提供者"""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        default_model: str = "gemini-pro",
        proxy: str | None = None,
        enabled: bool = True,
    ):
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

    def _merge_messages(self, messages: List[Dict[str, Any]]) -> str:
        """将 OpenAI 风格 message 列表合并为纯文本 prompt。"""
        parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            parts.append(f"{role}: {content}")
        return "\n".join(parts)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int = 150,
        temperature: float = 0.8,
    ) -> str:
        if not self.enabled:
            raise ProviderError("GeminiProvider disabled")

        prompt_text = self._merge_messages(messages)

        mdl_name = model or self._default_model

        model_obj = self._genai.GenerativeModel(mdl_name)

        response = model_obj.generate_content(
            prompt_text,
            generation_config={
                "max_output_tokens": max_tokens,
                "temperature": temperature,
            },
        )

        return response.text.strip()


class ClaudeProvider(BaseProvider):
    """Anthropic Claude provider via official SDK."""

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
        if proxy:
            self._client = anthropic.Anthropic(api_key=api_key, proxies={"http": proxy, "https": proxy})
        else:
            self._client = anthropic.Anthropic(api_key=api_key)
        self._default_model = default_model

    def chat(self, messages: List[Dict[str, Any]], *, model=None, max_tokens=150, temperature=0.8):  # noqa: D401
        if not self.enabled:
            raise ProviderError("ClaudeProvider disabled")

        # Anthropic expects system, assistant, user list without names.
        claude_msgs = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            claude_msgs.append({"role": role, "content": content})

        resp = self._client.messages.create(
            model=model or self._default_model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=claude_msgs,
        )
        return resp.content[-1].text.strip()  # type: ignore


class LocalProvider(BaseProvider):
    """调用本地 OpenAI-compatible LLM 端点，如 llama.cpp 或 ollama."""

    name = "local"

    def __init__(self, endpoint: str, default_model: str = "local-model", proxy: str | None = None, enabled: bool = True, timeout: float = 60.0):
        super().__init__(enabled)
        self._endpoint = endpoint.rstrip("/") + "/v1/chat/completions"
        self._default_model = default_model
        self._timeout = timeout
        self._proxy = proxy

    def chat(self, messages: List[Dict[str, Any]], *, model=None, max_tokens=150, temperature=0.8):  # noqa: D401
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
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"LocalProvider HTTP error: {exc}") from exc


class DummyProvider(BaseProvider):
    """占位符，暂未实现的模型。"""

    def __init__(self, name: str):
        super().__init__(enabled=False)
        self.name = name

    def chat(self, *args, **kwargs) -> str:  # noqa: D401, ANN002
        raise ProviderError(f"Provider {self.name} not implemented")


class LLMRouter:
    """
    统一的LLM调用路由。
    根据配置初始化所有启用的模型提供商，并按优先级顺序尝试调用。
    """
    # 定义了模型的优先级顺序
    PROVIDER_PRIORITY = ["gemini", "openai", "claude", "deepseek", "local"]

    def __init__(self, all_configs: Dict[str, str], deepseek_client_legacy=None):
        """
        从包含所有配置的字典初始化路由器。
        
        :param all_configs: 一个字典，包含从数据库读取的所有'key.name' -> 'value'配置。
        :param deepseek_client_legacy: (兼容旧版) 预初始化的DeepSeek客户端。
        """
        self.providers: List[BaseProvider] = []
        self._enabled_models: List[str] = []

        logger.info("🤖 初始化 LLM 路由器...")

        for provider_name in self.PROVIDER_PRIORITY:
            # 检查模型是否在数据库中被启用
            is_enabled = all_configs.get(f"DEFAULT.{provider_name}.enable", "no").lower() == "yes"
            
            if not is_enabled:
                logger.debug(f"LLM 提供商 '{provider_name}' 未启用，跳过。")
                continue

            try:
                provider_instance = None
                logger.info(f"正在配置已启用的 LLM 提供商: {provider_name}...")
                
                if provider_name == "deepseek":
                    # Deepseek 的 client 是在主程序中创建的，这里我们只使用它
                    # 但我们仍然需要检查它的配置是否完整
                    api_key = all_configs.get("DEFAULT.deepseek.api_key")
                    if not api_key:
                       raise ProviderError("DeepSeek 已启用但 API Key 未配置。")
                    if deepseek_client_legacy:
                       provider_instance = DeepSeekProvider(
                           client=deepseek_client_legacy,
                           default_model=all_configs.get("DEFAULT.deepseek.model", "deepseek-chat"),
                           enabled=True
                       )
                    else: # 如果旧版 client 不可用，则自己创建一个
                        base_url = all_configs.get("DEFAULT.deepseek.api_base", "https://api.deepseek.com/v1")
                        proxy = all_configs.get("DEFAULT.deepseek.proxy") or all_configs.get("NETWORK.proxy")
                        http_client = httpx.Client(proxies=proxy, timeout=60.0) if proxy else None
                        import openai
                        client = openai.OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)
                        provider_instance = DeepSeekProvider(client=client, default_model=all_configs.get("DEFAULT.deepseek.model", "deepseek-chat"), enabled=True)

                elif provider_name == "openai":
                    provider_instance = OpenAIProvider(
                        api_key=all_configs.get("DEFAULT.openai.api_key"),
                        base_url=all_configs.get("DEFAULT.openai.api_base", "https://api.openai.com/v1"),
                        default_model=all_configs.get("DEFAULT.openai.model", "gpt-4o"),
                        proxy=all_configs.get("DEFAULT.openai.proxy") or all_configs.get("NETWORK.proxy"),
                        enabled=True
                    )
                
                elif provider_name == "gemini":
                    provider_instance = GeminiProvider(
                        api_key=all_configs.get("DEFAULT.gemini.api_key"),
                        default_model=all_configs.get("DEFAULT.gemini.model", "gemini-1.5-pro-latest"),
                        proxy=all_configs.get("DEFAULT.gemini.proxy") or all_configs.get("NETWORK.proxy"),
                        enabled=True
                    )
                
                elif provider_name == "claude":
                    provider_instance = ClaudeProvider(
                        api_key=all_configs.get("DEFAULT.claude.api_key"),
                        default_model=all_configs.get("DEFAULT.claude.model", "claude-3-opus-20240229"),
                        proxy=all_configs.get("DEFAULT.claude.proxy") or all_configs.get("NETWORK.proxy"),
                        enabled=True
                    )

                elif provider_name == "local":
                    provider_instance = LocalProvider(
                        endpoint=all_configs.get("DEFAULT.local.endpoint"),
                        default_model=all_configs.get("DEFAULT.local.model", "local-model"),
                        proxy=all_configs.get("DEFAULT.local.proxy") or all_configs.get("NETWORK.proxy"),
                        enabled=True
                    )
                
                if provider_instance:
                    self.providers.append(provider_instance)
                    self._enabled_models.append(provider_name)
                    logger.info(f"✅ LLM 提供商 '{provider_name}' 加载成功。")

            except ProviderError as e:
                logger.error(f"❌ 加载 LLM 提供商 '{provider_name}' 失败: {e}")
            except Exception as e:
                logger.error(f"❌ 加载 LLM 提供商 '{provider_name}' 时发生意外错误: {e}")

        if not self.providers:
            logger.warning("⚠️ 没有成功加载任何 LLM 提供商，AI 回复功能将不可用。")

    def get_enabled_models(self) -> List[str]:
        """返回已启用并成功加载的提供商名称列表。"""
        return self._enabled_models

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str | None = None, # model 参数现在用于选择特定模型，如果未提供则按顺序尝试
        max_tokens: int = 150,
        temperature: float = 0.8,
    ) -> str:
        """
        按优先级顺序尝试调用提供商，直到成功为止。
        如果指定了 model，则只尝试该模型。
        """
        
        providers_to_try = self.providers
        # 如果指定了模型名称，则只使用对应的提供商
        if model:
            providers_to_try = [p for p in self.providers if p.name == model]
            if not providers_to_try:
                 raise ProviderError(f"指定的模型 '{model}' 未启用或未成功加载。")

        last_error: Exception | None = None
        for provider in providers_to_try:
            try:
                logger.info(f"▶️ 正在尝试使用 '{provider.name}' 模型...")
                return provider.chat(
                    messages=messages,
                    model=model, # 传递 model 参数给 provider
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except ProviderError as e:
                logger.warning(f"🟡 模型 '{provider.name}' 调用失败 (ProviderError): {e}")
                last_error = e
            except Exception as e:
                logger.error(f"🔴 模型 '{provider.name}' 调用时发生意外错误: {e}", exc_info=True)
                last_error = e
        
        logger.error("❌ 所有启用的 LLM 提供商都调用失败。")
        if last_error:
            raise last_error
        
        raise ProviderError("没有可用的 LLM 提供商。") 