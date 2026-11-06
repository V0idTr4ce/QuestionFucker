#!/usr/bin/env python3
"""本地题库检索 + llama.cpp/Qwen3-Coder 回答服务。仅使用 Python 标准库。"""

from __future__ import annotations

import atexit
import json
import mimetypes
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from prompt import SYSTEM_PROMPT, build_user_prompt
from retrieval import QuestionBank, format_context


SCRIPT_ROOT = Path(__file__).resolve().parent
ROOT = SCRIPT_ROOT.parent
STATIC = ROOT / "static"
LOGS = ROOT / "logs"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
APP_CONFIG = CONFIG.get("app", {})
BANK_CONFIG = CONFIG.get("question_bank", {})
LLAMA_CONFIG = CONFIG.get("llama", {})
GENERATION_CONFIG = CONFIG.get("generation", {})
RETRIEVAL_CONFIG = CONFIG.get("retrieval", {})


def resolve_config_path(value: str | os.PathLike[str]) -> Path:
    """配置中的相对路径均相对于 AI-search 目录。"""
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return path if path.is_absolute() else (ROOT / path).resolve()


QUESTION_FILE = resolve_config_path(BANK_CONFIG.get("path", "data/questions.jsonl"))
PAGE_FILE = resolve_config_path(APP_CONFIG.get("page_path", "static/index.html"))
LOGS.mkdir(exist_ok=True)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


STATE_LOCK = threading.Lock()
STATE: dict[str, Any] = {
    "phase": "starting",
    "message": "正在读取题库……",
    "ready": False,
    "model": "",
    "llama_url": "",
    "question_count": 0,
    "llama_owned": False,
}


def set_state(**values: Any) -> None:
    with STATE_LOCK:
        STATE.update(values)


def get_state() -> dict[str, Any]:
    with STATE_LOCK:
        return dict(STATE)


def http_json(url: str, payload: dict | None = None, timeout: float = 5) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


class LlamaManager:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.base_url = ""
        self.model_id = ""
        self.stdout_handle = None
        self.stderr_handle = None

    def probe(self, base: str) -> tuple[bool, str]:
        base = base.rstrip("/")
        try:
            health = http_json(base + "/health", timeout=2)
            models = http_json(base + "/v1/models", timeout=3)
            items = models.get("data") or models.get("models") or []
            ids = [str(x.get("id") or x.get("model") or x.get("name") or "") for x in items]
            expected = str(LLAMA_CONFIG.get("expected_model_keyword", "")).lower().strip()
            accept_any = bool(LLAMA_CONFIG.get("accept_any_loaded_model", False))
            matching = (ids[0] if ids else "") if (accept_any or not expected) else next((x for x in ids if expected in x.lower()), "")
            return health.get("status") == "ok" and bool(matching), matching
        except Exception:
            return False, ""

    def roots(self) -> list[Path]:
        values: list[str] = []
        if os.environ.get("LLAMA_CPP_HOME"):
            values.append(os.environ["LLAMA_CPP_HOME"])
        values.extend(str(x) for x in LLAMA_CONFIG.get("root_candidates", []))
        result: list[Path] = []
        seen: set[str] = set()
        for value in values:
            path = resolve_config_path(value)
            key = str(path).lower()
            if path.exists() and key not in seen:
                seen.add(key)
                result.append(path)
        return result

    def locate(self) -> tuple[Path, Path]:
        """定位服务程序和模型；显式配置/环境变量优先，其次自动发现。"""
        roots = self.roots()

        server_value = os.environ.get("LLAMA_SERVER_PATH") or str(LLAMA_CONFIG.get("server_path", "")).strip()
        server: Path | None = resolve_config_path(server_value) if server_value else None
        if server and not server.is_file():
            raise FileNotFoundError(f"config.json 中的 llama.server_path 不存在：{server}")
        if server is None:
            found_on_path = shutil.which("llama-server.exe") or shutil.which("llama-server")
            if found_on_path:
                server = Path(found_on_path).resolve()
        if server is None:
            for root in roots:
                server = next((root / p for p in LLAMA_CONFIG.get("server_relative_paths", []) if (root / p).is_file()), None)
                if server:
                    server = server.resolve()
                    break

        model_value = os.environ.get("LLAMA_MODEL_PATH") or str(LLAMA_CONFIG.get("model_path", "")).strip()
        model: Path | None = resolve_config_path(model_value) if model_value else None
        if model and not model.is_file():
            raise FileNotFoundError(f"config.json 中的 llama.model_path 不存在：{model}")
        if model is None:
            for root in roots:
                model = next((root / p for p in LLAMA_CONFIG.get("model_relative_paths", []) if (root / p).is_file()), None)
                if model:
                    model = model.resolve()
                    break
        if model is None:
            for root in roots:
                for pattern in LLAMA_CONFIG.get("model_globs", []):
                    matches = sorted((p.resolve() for p in root.glob(pattern) if p.is_file()), key=lambda p: p.stat().st_size, reverse=True)
                    if matches:
                        model = matches[0]
                        break
                if model:
                    break

        missing = []
        if server is None:
            missing.append("llama-server 可执行文件")
        if model is None:
            missing.append("GGUF 模型")
        if missing:
            checked = "、".join(str(x) for x in roots) or "未发现有效候选目录"
            raise FileNotFoundError(
                "未找到" + "和".join(missing) + f"。已检查：{checked}。"
                "请编辑 config.json 的 llama.server_path 和 llama.model_path。"
            )
        return server, model

    def ensure(self) -> None:
        configured_url = os.environ.get("AI_SEARCH_LLAMA_URL") or str(LLAMA_CONFIG.get("base_url", "http://127.0.0.1:8080"))
        parsed = urlparse(configured_url if "://" in configured_url else "http://" + configured_url)
        host = parsed.hostname or "127.0.0.1"
        preferred = parsed.port or 8080
        configured_url = f"{parsed.scheme or 'http'}://{host}:{preferred}"
        set_state(phase="checking_llama", message=f"正在检查 {configured_url} 的 llama.cpp……")

        ok, model_id = self.probe(configured_url)
        if ok:
            self.base_url = configured_url
            self.model_id = model_id
            set_state(phase="ready", message="已连接现有 llama.cpp，模型已加载", ready=True,
                      model=model_id, llama_url=self.base_url, llama_owned=False)
            return

        if not bool(LLAMA_CONFIG.get("auto_start", True)):
            raise RuntimeError(f"无法连接 {configured_url}，且 config.json 中 llama.auto_start=false")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError(f"无法连接远程 llama.cpp：{configured_url}；远程地址不会由本程序自动启动")

        # 如果首选端口被其他服务/模型占用，不终止它，自动寻找备用端口。
        selected = None
        fallback_end = int(LLAMA_CONFIG.get("fallback_port_end", preferred + 10))
        for port in range(preferred, fallback_end + 1):
            if not port_open(host, port):
                selected = port
                break
        if selected is None:
            raise RuntimeError(f"{preferred}—{fallback_end}端口均被占用，无法启动专用 llama-server")

        server, model = self.locate()
        set_state(phase="loading_model", message=f"正在端口 {selected} 加载 {model.name}……",
                  server_path=str(server), model_path=str(model))
        args = [str(server), "-m", str(model)]
        optional_args = [
            ("-ngl", LLAMA_CONFIG.get("gpu_layers")),
            ("-c", LLAMA_CONFIG.get("context_size")),
            ("-t", LLAMA_CONFIG.get("threads")),
            ("--parallel", LLAMA_CONFIG.get("parallel")),
        ]
        for flag, value in optional_args:
            if value is not None and str(value).strip() != "":
                args.extend((flag, str(value)))
        args.extend(("--host", host, "--port", str(selected)))
        args.extend(str(x) for x in LLAMA_CONFIG.get("extra_server_args", []))
        env = os.environ.copy()
        bin_dir = str(server.parent)
        runtime_dirs = [resolve_config_path(x) for x in LLAMA_CONFIG.get("runtime_library_dirs", [])]
        cuda_home = os.environ.get("CUDA_PATH")
        if cuda_home:
            runtime_dirs.extend((Path(cuda_home) / "bin", Path(cuda_home) / "bin" / "x64"))
        # Windows 上 CUDA_PATH 并不总会由安装器写入环境变量；自动加入已安装的
        # CUDA Toolkit 目录，避免分发后因版本号不同而要求用户修改固定路径。
        if os.name == "nt":
            program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            cuda_root = program_files / "NVIDIA GPU Computing Toolkit" / "CUDA"
            if cuda_root.is_dir():
                for candidate in sorted(cuda_root.glob("v*"), reverse=True):
                    runtime_dirs.extend((candidate / "bin", candidate / "bin" / "x64"))
        valid_runtime_dirs = [str(x) for x in runtime_dirs if x.exists()]
        env["PATH"] = os.pathsep.join([bin_dir, *valid_runtime_dirs, env.get("PATH", "")])
        self.stdout_handle = (LOGS / "llama.stdout.log").open("ab")
        self.stderr_handle = (LOGS / "llama.stderr.log").open("ab")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.process = subprocess.Popen(
            args, cwd=str(server.parent), env=env,
            stdout=self.stdout_handle, stderr=self.stderr_handle,
            creationflags=creationflags,
        )
        self.base_url = f"http://{host}:{selected}"
        set_state(llama_owned=True, llama_url=self.base_url)
        deadline = time.time() + int(LLAMA_CONFIG.get("start_timeout_seconds", 360))
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"llama-server 启动失败，退出码 {self.process.returncode}；请查看 logs/llama.stderr.log")
            ok, model_id = self.probe(self.base_url)
            if ok:
                self.model_id = model_id
                set_state(phase="ready", message=f"llama.cpp 已启动，{model.name} 已加载", ready=True,
                          model=model_id, llama_url=self.base_url, llama_owned=True)
                return
            time.sleep(2)
        raise TimeoutError("模型加载超时；请查看 logs/llama.stderr.log")

    def chat(self, question: str, context: str, reliable: bool) -> str:
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(question, context, reliable)},
            ],
            "temperature": GENERATION_CONFIG.get("temperature", 0.1),
            "top_p": GENERATION_CONFIG.get("top_p", 0.9),
            "max_tokens": GENERATION_CONFIG.get("max_answer_tokens", 1200),
            "stream": False,
        }
        result = http_json(self.base_url + "/v1/chat/completions", payload, timeout=int(LLAMA_CONFIG.get("request_timeout_seconds", 300)))
        choices = result.get("choices") or []
        if not choices:
            raise RuntimeError("llama.cpp 未返回回答")
        message = choices[0].get("message") or {}
        content = str(message.get("content") or "").strip()
        if not content:
            content = str(message.get("reasoning_content") or "").strip()
        # 个别模板可能把内部思考包在 think 标签中；只展示标签后的最终回答。
        if "</think>" in content:
            content = content.split("</think>", 1)[1].strip()
        if not content:
            raise RuntimeError("模型回答为空")
        return content

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        for handle in (self.stdout_handle, self.stderr_handle):
            if handle:
                handle.close()


if not QUESTION_FILE.exists():
    raise FileNotFoundError(f"找不到题库：{QUESTION_FILE}")
BANK = QuestionBank(QUESTION_FILE)
set_state(question_count=len(BANK.questions), message=f"已读取 {len(BANK.questions)} 道题，正在检查模型……")
LLAMA = LlamaManager()
atexit.register(LLAMA.close)


def boot_model() -> None:
    try:
        LLAMA.ensure()
    except Exception as exc:
        set_state(phase="error", message=str(exc), ready=False)
        print(f"[模型启动失败] {exc}", file=sys.stderr, flush=True)


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "HaifengAI/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def send_json(self, value: Any, status: int = 200) -> None:
        body = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # 允许由 file:// 打开的小窗搜题页调用本机 API。
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > 200_000:
            raise ValueError("请求内容为空或过大")
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def do_GET(self) -> None:
        if self.path == "/api/status":
            self.send_json(get_state())
            return
        path = self.path.split("?", 1)[0]
        if path in ("/", ""):
            requested = PAGE_FILE
        elif path == "/data/questions.js" and QUESTION_FILE.suffix.lower() == ".js":
            requested = QUESTION_FILE
        else:
            requested = (STATIC / path.lstrip("/")).resolve()
            if STATIC.resolve() not in requested.parents and requested != STATIC.resolve():
                self.send_error(403)
                return
        if not requested.is_file():
            self.send_error(404)
            return
        body = requested.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(str(requested))[0] or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/api/ask":
            state = get_state()
            if not state.get("ready"):
                self.send_json({"error": state.get("message", "模型尚未就绪")}, 503)
                return
            try:
                question = str(self.read_json().get("question") or "").strip()
                if len(question) < 2:
                    raise ValueError("请输入题目")
                if len(question) > 20_000:
                    raise ValueError("题目过长")
                matches = BANK.search(question, int(RETRIEVAL_CONFIG.get("top_k", 6)))
                context, reliable = format_context(matches, float(RETRIEVAL_CONFIG.get("reliable_match_threshold", 0.55)))
                answer = LLAMA.chat(question, context, reliable)
                candidates = []
                for match in matches[:3]:
                    q = match.question
                    opts = q.get("options") or {}
                    candidates.append({
                        "score": round(match.score, 3),
                        "stem": q.get("stem", ""),
                        "answer": "；".join(f"{a}. {opts.get(a, '')}" for a in q.get("answer", [])),
                    })
                self.send_json({
                    "answer": answer,
                    "retrieval_reliable": reliable,
                    "route": "题库优先并由模型核验" if reliable else "题库无可靠命中，使用模型知识",
                    "candidates": candidates,
                })
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                self.send_json({"error": f"模型接口错误 HTTP {exc.code}: {detail[:500]}"}, 502)
            except Exception as exc:
                self.send_json({"error": str(exc)}, 500)
            return
        if self.path == "/api/shutdown":
            self.send_json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self.send_error(404)


def main() -> None:
    host, port = APP_CONFIG.get("host", "127.0.0.1"), int(APP_CONFIG.get("port", 8765))
    threading.Thread(target=boot_model, daemon=True).start()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"AI 搜题服务：http://{host}:{port}，题库 {len(BANK.questions)} 道", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        LLAMA.close()


if __name__ == "__main__":
    main()
