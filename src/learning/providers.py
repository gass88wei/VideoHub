"""Small provider boundary: no secrets in responses, no hidden paid fallbacks."""

from __future__ import annotations

import json
import os
import re
import threading
from urllib.parse import urlsplit

import requests

DEFAULTS = {
    "deepseek": {"label": "DeepSeek", "base": "https://api.deepseek.com", "model": "deepseek-flash"},
    "kimi": {"label": "Kimi", "base": "https://api.moonshot.cn/v1", "model": "kimi-k2.6"},
}
SETTING_KEY = "providers"

_store = None


def bind(store):
    """Point provider configuration at the learning store (settings table)."""
    global _store
    _store = store


def saved(name: str) -> dict:
    """Configuration entered in the UI, empty when the provider is untouched."""
    if _store is None:
        return {}
    value = _store.setting(SETTING_KEY, {})
    item = value.get(name) if isinstance(value, dict) else None
    return item if isinstance(item, dict) else {}


def clean_base(value: str) -> str:
    """Accept what people copy from a provider console, reject cleartext remote URLs."""
    url = str(value or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
    if not url:
        raise ValueError("请填写 API 地址，例如 https://api.deepseek.com")
    if len(url) > 300:
        raise ValueError("API 地址过长")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("API 地址需以 http:// 或 https:// 开头")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("远程 API 地址必须使用 HTTPS，只有本机地址可以用 HTTP")
    return url


def clean_model(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("请填写模型名称")
    if len(name) > 120 or not re.fullmatch(r"[A-Za-z0-9_./:-]+", name):
        raise ValueError("模型名称无效")
    return name


def clean_key(value: str) -> str:
    key = str(value or "").strip()
    if len(key) > 512 or any(c.isspace() for c in key):
        raise ValueError("API 密钥格式无效")
    return key


def save(name: str, data: dict) -> dict:
    """Merge one provider's settings; an omitted field keeps its saved value."""
    if name not in DEFAULTS:
        raise ValueError("支持 DeepSeek 或 Kimi")
    if _store is None:
        raise ValueError("配置存储未初始化")
    item = dict(saved(name))
    if data.get("base_url") is not None:
        item["base_url"] = clean_base(data["base_url"])
    if data.get("model") is not None:
        item["model"] = clean_model(data["model"])
    if data.get("api_key"):
        item["api_key"] = clean_key(data["api_key"])
    elif data.get("clear_key") is True:
        item.pop("api_key", None)
    current = _store.setting(SETTING_KEY, {}) or {}
    merged = {**(current if isinstance(current, dict) else {}), name: item}
    _store.save_setting(SETTING_KEY, merged)
    return item


def describe(name: str) -> dict:
    """Everything the settings panel may know: never the secret itself."""
    try:
        provider = Provider(name)
    except ValueError as error:
        return {"label": DEFAULTS[name]["label"], "configured": False, "model": "", "base_url": "",
                "input_budget": 24000, "key_hint": "", "source": "none", "error": str(error)}
    item = saved(name)
    key = provider.key
    return {
        "label": DEFAULTS[name]["label"],
        "configured": bool(key),
        "model": provider.model,
        "base_url": provider.base,
        "default_base_url": DEFAULTS[name]["base"],
        "input_budget": provider.budget,
        "key_hint": ("…" + key[-4:]) if len(key) >= 8 else ("已保存" if key else ""),
        "source": "settings" if item.get("api_key") else ("env" if key else "none"),
        "official": provider.official,
    }


class Provider:
    def __init__(self, name: str = "deepseek", model: str = "", base_url: str = "", api_key: str = ""):
        if name not in DEFAULTS:
            raise ValueError("支持 DeepSeek 或 Kimi")
        self.name = name
        item = saved(name)
        prefix = "DEEPSEEK" if name == "deepseek" else "MOONSHOT"
        self.key = (
            clean_key(api_key)
            or str(item.get("api_key") or "").strip()
            or os.getenv(prefix + "_API_KEY", "").strip()
        )
        if name == "kimi" and not self.key:
            self.key = os.getenv("KIMI_API_KEY", "").strip()
        self.base = clean_base(
            base_url or item.get("base_url") or os.getenv(prefix + "_BASE_URL") or DEFAULTS[name]["base"]
        )
        self.official = urlsplit(self.base).hostname == urlsplit(DEFAULTS[name]["base"]).hostname
        self.model = clean_model(
            str(model).strip()
            or str(item.get("model") or "").strip()
            or os.getenv(prefix + "_MODEL", "").strip()
            or DEFAULTS[name]["model"]
        )
        # Conservative byte budget is an upper bound on typical byte-pair token counts.
        try:
            self.budget = min(100_000, max(6000, int(os.getenv("LEARNING_INPUT_BUDGET", "24000"))))
        except ValueError:
            self.budget = 24000

    def require_key(self):
        if not self.key:
            raise ValueError(
                "未配置 " + DEFAULTS[self.name]["label"] + " 的 API 密钥，请在右侧「模型设置」里填写"
            )

    def payload(self, messages: list[dict], max_tokens: int, stream: bool) -> dict:
        value = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "stream": stream}
        # Ask the two official endpoints to answer directly; other OpenAI-compatible
        # servers reject unknown parameters, so only send this when they understand it.
        if self.official and (self.name == "deepseek" or "k2.6" in self.model):
            value["thinking"] = {"type": "disabled"}
        return value

    def endpoint(self, path: str) -> str:
        """Join path onto the base, tolerating the /v1 suffix being present or absent.

        People copy either form from provider consoles; /chat/completions and
        /v1/chat/completions both exist on the official servers.
        """
        base = self.base
        if not base.endswith("/v1") and path.startswith("/chat"):
            base = base + "/v1"
        return base + path

    def probe(self, timeout: int = 25) -> dict:
        """One small non-streaming request used by the settings panel."""
        self.require_key()
        try:
            response = requests.post(
                self.endpoint("/chat/completions"),
                headers={"Authorization": "Bearer " + self.key},
                json=self.payload([{"role": "user", "content": "ping"}], 16, False),
                timeout=(10, timeout),
            )
        except requests.RequestException:
            raise ValueError("连接失败：地址不可达或超时，请检查 API 地址和网络") from None
        if response.status_code != 200:
            raise ValueError(provider_error(self.name, response.status_code, response))
        try:
            data = response.json()
        except ValueError:
            raise ValueError("接口返回的不是 JSON，请确认这是 OpenAI 兼容的 API 地址") from None
        if data.get("error"):
            raise ValueError("接口返回错误：" + str(data["error"])[:160])
        reply = data.get("model") or self.model
        return {"ok": True, "model": str(reply), "base_url": self.base}

    def stream(self, messages: list[dict], cancelled: threading.Event, max_tokens: int = 2200):
        self.require_key()
        if sum(len(m["content"].encode("utf-8")) + 32 for m in messages) > self.budget:
            raise ValueError("本次上下文超过配置预算，请缩小选段或提高 LEARNING_INPUT_BUDGET")
        payload = self.payload(messages, max_tokens, True)
        payload["stream_options"] = {"include_usage": True}
        if cancelled.is_set():
            raise InterruptedError()
        try:
            with requests.post(
                self.endpoint("/chat/completions"),
                headers={"Authorization": "Bearer " + self.key},
                json=payload,
                stream=True,
                timeout=(10, 60),
            ) as response:
                if response.status_code != 200:
                    raise ValueError(provider_error(self.name, response.status_code, response))
                response.encoding = "utf-8"
                finish, received = None, False
                for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                    if cancelled.is_set():
                        raise InterruptedError()
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        raise ValueError("模型返回了无法解析的数据流") from None
                    if data.get("error"):
                        raise ValueError("模型服务在回复过程中返回错误，请稍后重试")
                    if data.get("usage"):
                        yield {"usage": data["usage"]}
                    for choice in data.get("choices", []):
                        content = choice.get("delta", {}).get("content")
                        if content:
                            received = True
                            yield {"text": content}
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
                if finish != "stop":
                    raise ValueError(
                        "模型回复未完整结束" + ("（达到输出长度限制）" if finish == "length" else "，请重试")
                    )
                if not received:
                    raise ValueError("模型未返回正文，请检查模型配置")
        except requests.RequestException:
            if cancelled.is_set():
                raise InterruptedError() from None
            raise ValueError("模型服务连接失败或超时，请检查网络后重试") from None

    def complete(self, messages, cancelled, max_tokens=1200) -> tuple[str, dict | None]:
        text, usage = "", None
        for event in self.stream(messages, cancelled, max_tokens):
            text += event.get("text", "")
            usage = event.get("usage", usage)
        return text, usage


def provider_error(name: str, status: int, response=None) -> str:
    label = DEFAULTS[name]["label"] if name in DEFAULTS else name
    detail = {
        400: "请求参数或模型名称不被支持",
        401: "密钥无效",
        402: "余额不足",
        403: "账户无此接口权限",
        404: "模型或接口不存在",
        429: "触发限流，请稍后重试",
    }.get(status, "服务暂不可用")
    hint = ""
    if response is not None and status in {400, 404, 422}:
        try:
            body = response.json()
            message = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
            message = str(message or body.get("message") or "").strip()
            if message:
                hint = "：" + message[:160]
        except ValueError:
            pass
    return f"{label}：{detail}{hint}（HTTP {status}）"


def json_result(text: str):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("模型未返回有效的结构化结果，请重试") from None


def capabilities() -> dict:
    return {name: describe(name) for name in DEFAULTS}
