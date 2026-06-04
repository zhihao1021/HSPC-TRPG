"""集中式設定:所有設定皆從環境變數讀取,於 main.py 載入 .env 後使用。"""
from os import getenv
from pathlib import Path
from typing import Optional, overload

PROMPTS_DIR = Path(__file__).parent / "prompts"


@overload
def _get(name: str) -> Optional[str]: ...


@overload
def _get(name: str, default: str) -> str: ...


def _get(name: str, default: Optional[str] = None) -> Optional[str]:
    value = getenv(name, default)
    if value is not None:
        value = value.strip()
    return value or default


def _get_required(name: str) -> str:
    value = _get(name)
    if not value:
        raise ValueError(f"環境變數 {name} 未設定")
    return value


def _get_int(name: str, default: int) -> int:
    value = _get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    value = _get(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


# ---- Discord ----
def discord_token() -> str:
    return _get_required("DISCORD_BOT_TOKEN")


# ---- Database ----
def postgres_dsn() -> str:
    return _get(
        "POSTGRES_DB_URL",
        "postgresql://hspc:hspc@localhost:5432/hspc_trpg",
    )


def postgres_pool_min() -> int:
    return _get_int("POSTGRES_POOL_MIN_SIZE", 5)


def postgres_pool_max() -> int:
    return _get_int("POSTGRES_POOL_MAX_SIZE", 10)


# ---- LLM (Deepseek 官方 API) ----
def llm_api_key() -> str:
    return _get_required("DEEPSEEK_API_KEY")


def llm_base_url() -> str:
    return _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def llm_model() -> str:
    return _get("DEEPSEEK_MODEL", "deepseek-v4-flash")


def summary_model() -> str:
    return _get("CONTEXT_SUMMARY_MODEL") or llm_model()


def chargen_model() -> str:
    return _get("CHARGEN_MODEL") or llm_model()


def llm_reasoning_enabled() -> bool:
    return _get_bool("DEEPSEEK_REASONING_ENABLED", False)

def chargen_reasoning_enabled() -> bool:
    return _get_bool("CHARGEN_REASONING_ENABLED", False)


def llm_temperature() -> float:
    try:
        return float(_get("DEEPSEEK_TEMPERATURE", "1.0"))
    except ValueError:
        return 1.0


def llm_max_tokens() -> int:
    return _get_int("DEEPSEEK_MAX_TOKENS", 4096)


def llm_max_tool_iterations() -> int:
    """單次回應中,tool-calling 迴圈的最大往返次數,避免無限迴圈。"""
    return _get_int("LLM_MAX_TOOL_ITERATIONS", 8)


# ---- Context 管理 ----
def _get_float(name: str, default: float) -> float:
    value = _get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def context_window() -> int:
    """模型的 context window 總大小(token)。Deepseek v4 約為 1M。"""
    return _get_int("CONTEXT_WINDOW", 1_000_000)


def context_trigger_ratio() -> float:
    """當 prompt token 用量超過 window 的此比例時觸發壓縮(0.75 = 75%)。"""
    return _get_float("CONTEXT_TRIGGER_RATIO", 0.75)


def context_compress_ratio() -> float:
    """壓縮後的目標:把 context 縮減到 window 的此比例(壓縮比率)。"""
    return _get_float("CONTEXT_COMPRESS_RATIO", 0.5)


def context_trigger_tokens() -> int:
    """觸發壓縮的絕對 token 門檻 = window * trigger_ratio。"""
    return int(context_window() * context_trigger_ratio())


def context_target_tokens() -> int:
    """壓縮後欲達到的目標 token 量 = window * compress_ratio。"""
    return int(context_window() * context_compress_ratio())


def context_keep_recent() -> int:
    """壓縮時至少保留的最近訊息則數。"""
    return _get_int("CONTEXT_KEEP_RECENT", 40)


def context_max_fetch() -> int:
    """組裝請求時最多撈取的歷史訊息則數。"""
    return _get_int("CONTEXT_MAX_FETCH", 400)


# ---- 晉級名單 ----
def roster_file() -> str:
    return _get("ROSTER_FILE", "data/roster.json")


def revealed_dir() -> str:
    """已公布名單輸出目錄;每個頻道會寫入一份 <channel_id>.json。"""
    return _get("REVEALED_DIR", "data/revealed")


def show_reasoning() -> bool:
    """是否將模型的 thinking 內容輸出到 Discord(預設關閉)。"""
    return _get_bool("SHOW_REASONING", False)
