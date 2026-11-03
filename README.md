# 海丰杯“QuestionFucker”理论题库

可直接发布、下载和离线使用的单文件页面题库，并可选连接本地 `llama.cpp` 模型辅助答题。

## 功能

- 输入即搜索本地题库，不调用 AI；
- 只有主动点击“问 AI”才访问本地模型；
- AI 回答前先检索题库，未可靠命中时再使用模型自身知识；
- 题库独立存放在 `data/questions.js`，前端和 AI 检索共用同一份数据；
- 不需要安装任何 Python 第三方包。

## 快速使用

### 只使用本地题库

直接双击 `QuestionFucker.html`。页面可以通过 `file://` 离线运行。

### 使用本地 AI

运行环境：Windows 10/11、Python 3.10或更高版本，以及以下任一种模型环境：

1. 已运行的、兼容 OpenAI 接口的 `llama.cpp` 服务；
2. 本地 `llama-server.exe` 和 GGUF 模型文件。

首次使用：

1. 编辑 `config.json`；
2. 双击 `检查AI配置.bat`；
3. 检查通过后双击 `启动QuestionFuckerAI.bat`；
4. 使用结束后双击 `停止AI服务.bat`。

## 模型配置

### 复用已经运行的 llama.cpp

修改 `config.json` 中的 `llama`：

```json
"base_url": "http://127.0.0.1:8080",
"auto_start": false,
"expected_model_keyword": "Qwen3-Coder-30B-A3B-Instruct"
```

若允许使用服务中已经加载的任意模型，可设置：

```json
"accept_any_loaded_model": true
```

服务应兼容以下接口：

```text
GET  /health
GET  /v1/models
POST /v1/chat/completions
```

### 由程序自动启动模型

最稳定的方式是填写完整路径：

```json
"server_path": "D:/llama_cpp/bin/llama-server.exe",
"model_path": "E:/models/Qwen3-30B-A3B.gguf",
"auto_start": true,
"expected_model_keyword": "Qwen3-30B-A3B"
```

路径建议使用 `/` 或双反斜杠。留空时程序会依次尝试环境变量、系统 `PATH`、`root_candidates` 和模型通配规则。

Python不在系统 `PATH` 时，在 `app.python_executable` 中填写 `python.exe` 完整路径。

## 性能配置

- `gpu_layers`：GPU卸载层数；纯CPU运行设为 `0`；
- `context_size`：上下文长度，显存不足时调低；
- `threads`：CPU线程数；
- `runtime_library_dirs`：额外CUDA运行库路径，通常保持空数组；
- `max_answer_tokens`：单次回答最大生成长度。

程序会读取 `CUDA_PATH`，并自动扫描Windows常见CUDA安装目录。

## 端口

- 搜题API默认使用 `8765`；小窗页面会自动探测 `8765—8790`；
- llama.cpp默认使用 `8080`；冲突时自动尝试配置范围内的备用端口；
- 服务默认只监听 `127.0.0.1`。

运行时生成的 `logs/` 和 `__pycache__/` 已通过 `.gitignore` 排除。
