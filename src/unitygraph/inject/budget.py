"""Token-count + budget enforcement for injected context blocks.

Uses ``tiktoken`` with OpenAI's ``cl100k_base`` encoding — that's a decent
proxy for Claude's own tokenizer when we only need *approximate* counts to
stay under a budget. The only guarantee the spec §2.7 requires is that the
injected context stays under ``--budget`` (default 1500 tokens).
"""

from __future__ import annotations

from functools import lru_cache

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None  # type: ignore[assignment]


@lru_cache(maxsize=1)
def _encoding() -> object | None:
    if tiktoken is None:  # pragma: no cover
        return None
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    enc = _encoding()
    if enc is None:
        # Fallback: whitespace-delimited word count (overestimates slightly).
        return len(text.split())
    return len(enc.encode(text))  # type: ignore[attr-defined]


def fits_budget(text: str, budget: int) -> bool:
    return count_tokens(text) <= budget
