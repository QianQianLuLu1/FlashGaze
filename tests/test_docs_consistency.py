"""M-20 文档一致性守门：SKILL.md / README.md 不得回归已废弃的 LiteLLM 旧口径。

真源：flashgaze/core/vlm_client.py 的 `_post_with_retry` —— 所有 provider
（qwen/openai/anthropic/ollama）默认走内置 pin-IP 直连层，litellm 仅为
`VLMClient(use_litellm=True)` 的可选 opt-in 后端；`litellm_not_installed`
错误码已从实现中移除（opt-in 且未安装时降级为 `retry_exhausted`）。

对应审查项：docs/review/代码质量与架构审查报告.md M-20。
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 已废弃的「LiteLLM 统一接入 / 非 qwen 需装 litellm」旧口径与已移除的错误码。
# 清单为带上下文的精确短语，避免误伤合法的 opt-in 后端表述（如「可选 LiteLLM 后端」）。
FORBIDDEN_SUBSTRINGS: dict[str, tuple[str, ...]] = {
    "SKILL.md": (
        "litellm_not_installed",
        "基于 LiteLLM 统一接入",
        "通过 LiteLLM 统一调用层",
        "经 LiteLLM 路由",
        "留空走 LiteLLM 默认",
        "（需 litellm",
    ),
    "README.md": (
        "litellm_not_installed",
        "Multi-VLM providers via LiteLLM",
        "多 VLM 提供商（LiteLLM",
    ),
}

# 「默认 pin-IP 直连、litellm 仅 opt-in 兜底」正确口径的关键锚点，防止被改回旧口径。
REQUIRED_SUBSTRINGS: dict[str, tuple[str, ...]] = {
    "SKILL.md": (
        "pin-IP 直连",
        "use_litellm",
        "内置 pin 直连层",
    ),
    "README.md": (
        "optional LiteLLM backend",
        "可选 opt-in 后端",
    ),
}


def _read_doc(doc_name: str) -> str:
    return (REPO_ROOT / doc_name).read_text(encoding="utf-8")


@pytest.mark.parametrize("doc_name", sorted(FORBIDDEN_SUBSTRINGS))
def test_docs_do_not_contain_deprecated_litellm_claims(doc_name: str) -> None:
    doc = _read_doc(doc_name)
    for needle in FORBIDDEN_SUBSTRINGS[doc_name]:
        assert needle not in doc, (
            f"{doc_name} 回归了已废弃的 LiteLLM 旧口径：发现 {needle!r}。"
            f"请以 flashgaze/core/vlm_client.py 的 _post_with_retry 路由为准"
            f"（默认 pin-IP 直连，litellm 仅 use_litellm=True 的 opt-in 后端；"
            f"litellm_not_installed 错误码已不存在，降级为 retry_exhausted）。"
        )


@pytest.mark.parametrize("doc_name", sorted(REQUIRED_SUBSTRINGS))
def test_docs_document_pinned_direct_connect_default(doc_name: str) -> None:
    doc = _read_doc(doc_name)
    for needle in REQUIRED_SUBSTRINGS[doc_name]:
        assert needle in doc, (
            f"{doc_name} 缺少「默认 pin-IP 直连」口径的关键描述：{needle!r}。"
            f"请对照 flashgaze/core/vlm_client.py 的 _post_with_retry / _post_pinned_requests。"
        )
