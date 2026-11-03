#!/usr/bin/env python3
"""检查 config.json、题库、llama.cpp 接口以及自动启动所需路径。"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

from retrieval import load_questions


SCRIPT_ROOT = Path(__file__).resolve().parent
ROOT = SCRIPT_ROOT.parent
CONFIG_PATH = ROOT / "config.json"


def resolve(value: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    return path if path.is_absolute() else (ROOT / path).resolve()


def get_json(url: str, timeout: int = 3) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    print("=== 海丰杯 AI 搜题配置检查 ===")
    print(f"Python: {sys.executable}")
    print(f"版本: {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print("[失败] 需要 Python 3.10 或更高版本。")
        return 2
    try:
        config = json.loads(CONFIG_PATH.read_text("utf-8"))
    except Exception as exc:
        print(f"[失败] config.json 无法读取：{exc}")
        return 2

    bank_cfg = config.get("question_bank", {})
    bank = resolve(str(bank_cfg.get("path", "data/questions.jsonl")))
    if bank.is_file():
        count = len(load_questions(bank))
        print(f"[正常] 题库：{bank}（{count}道）")
    else:
        print(f"[失败] 找不到题库：{bank}")
        return 2

    llama = config.get("llama", {})
    base = str(os.environ.get("AI_SEARCH_LLAMA_URL") or llama.get("base_url", "http://127.0.0.1:8080")).rstrip("/")
    expected = str(llama.get("expected_model_keyword", "")).lower()
    running = False
    try:
        health = get_json(base + "/health")
        models = get_json(base + "/v1/models")
        items = models.get("data") or models.get("models") or []
        ids = [str(x.get("id") or x.get("model") or x.get("name") or "") for x in items]
        matches = bool(ids) and (bool(llama.get("accept_any_loaded_model")) or not expected or any(expected in x.lower() for x in ids))
        running = health.get("status") == "ok" and matches
        if running:
            print(f"[正常] 已运行的 llama.cpp：{base}")
            print(f"[正常] 已加载模型：{ids[0]}")
        else:
            print(f"[提示] {base} 可访问，但模型与 expected_model_keyword 不匹配：{ids}")
    except Exception as exc:
        print(f"[提示] 当前未连接到 {base}：{exc}")

    if not running and llama.get("auto_start", True):
        try:
            # 复用主程序的跨平台定位逻辑，但不启动模型。
            from app import LLAMA
            server, model = LLAMA.locate()
            print(f"[正常] 自动启动程序：{server}")
            print(f"[正常] 自动加载模型：{model}")
        except Exception as exc:
            print(f"[失败] 无法自动启动：{exc}")
            return 3
    elif not running:
        print("[提示] auto_start=false；请确保外部 llama.cpp 服务在使用前已经运行。")

    print("配置检查完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
