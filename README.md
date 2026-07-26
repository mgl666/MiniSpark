# MiniSpark

> A lightweight Agent framework designed for low-resource environments, focused on minimal memory footprint, high extensibility, and deep customization.
>
> It runs on servers with just 1GB of RAM. Compared to typical Agent frameworks, it minimizes unnecessary dependencies and runtime overhead while maintaining a clean, flexible modular structure — making it easy to extend model providers, tools, memory systems, message channels, and task scheduling as needed.
>
> Use it as a lightweight, customizable Agent foundation for building personal assistants or automation services — or as a teaching-oriented project for reading, debugging, and understanding how Agents work under the hood.
>
> 这是一个面向低资源环境设计的轻量级 Agent 框架，专注于低内存占用、高可扩展性与深度定制能力。
>
> 项目可在仅有 1GB 内存的服务器上运行。相比常见的 Agent 框架，它尽量减少不必要的依赖与运行开销，同时保留清晰、灵活的模块化结构，便于开发者根据实际需求扩展模型供应商、工具、记忆系统、消息通道和任务调度等功能。
>
> 你既可以将它作为一个轻量、可定制的 Agent 基础框架，用于构建个人助手或自动化服务；也可以将它视为一个便于阅读、调试和学习 Agent 工作原理的教学型项目。

---

<p align="center">
  <b>English</b> ｜ <a href="#中文">中文</a>
</p>

---

## Why MiniSpark?

| | Typical Agent Frameworks | MiniSpark |
|---|---|---|
| RAM Usage | 500MB ~ 2GB+ | **< 100MB** (pure Python, zero external services) |
| Dependencies | PostgreSQL / Redis / Docker | **SQLite only** (single file) |
| Configuration | env vars + YAML + code | **One config.toml** |
| Adding Tools | Write JSON Schema + adapter | **Write a Python function with type hints** |
| Model Switching | Edit env vars, restart | **`/model` — one command, API auto-discovery** |
| Multi-Channel | Usually CLI only | **CLI / QQ / Email — one Agent, three channels** |

> **Core philosophy:** Turn LLMs into real assistants that get things done, not just chatbots. MiniSpark focuses on doing four things exceptionally well: Agent loop, tool system, memory, and scheduled tasks. Everything else is handled by your `config.toml`.

---

## Architecture

```mermaid
flowchart TD
    subgraph CH["📨 Channels"]
        CLI["⌨️ CLI"]  QQ["💬 QQ"]  EM["📧 Email"]
    end
    GW["🚪 Gateway"]
    SCH["⏰ Scheduler"]
    AC[["🧠 Agent Core"]]
    PV["🤖 Provider<br/>OpenAI Compatible"]
    MEM[("🗃️ Memory<br/>SQLite")]
    subgraph TL["🧰 Tools"]
        FC["🔧 Function Call"]  SK["📚 Skills"]  MCP["🔌 MCP"]
    end
    CH --> GW --> AC
    SCH --> AC
    AC --> PV --> LLM["🌐 LLM API / LiteLLM Proxy"]
    AC --> TL
    AC --> MEM
```

---

## Quick Start

```bash
# 1. Install
cd MiniSpark
pip install -e .

# 2. Configure — just edit one file
#    Fill in your API key in config.toml
[provider]
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key = "sk-your-key"

# 3. Run
python -m minispark chat
```

```
You: Write a Python script to fetch weather every hour and save to weather.csv
MiniSpark: (calls write_file, schedule_task) ✅ Script + scheduled task created
```

---

## Key Features

### 🧠 Agent Loop
Auto request LLM → execute tools → feed results back → loop until done. 20-turn circuit breaker + context overflow self-healing + auto context compaction.

### 🧰 17 Built-in Tools

| Module | Tools |
|---|---|
| `fs` | `read_file` `write_file` `append_file` `edit_file` `list_dir` |
| `shell` | `run_shell` (allowlist/blocklist + human confirmation) |
| `web` | `web_search` `web_fetch` |
| `memory` | `memory_save` `memory_search` `memory_update` `memory_forget` |
| `schedule` | `schedule_task` `list_tasks` `cancel_task` |
| `email` | `send_email` |
| `skill` | `use_skill` (progressive disclosure) |

**Add a new tool = write one Python function with type hints.** The framework auto-generates OpenAI-compatible JSON Schema.

### 📚 Skills System
Pre-defined workflow prompts with progressive disclosure: only name + description are injected into the system prompt; full instructions are loaded on-demand via `use_skill`, saving tokens.

### 🔌 MCP Protocol
Connect external MCP servers — remote tools auto-register as local tools, unified with built-in FC tools.

### 🗃️ Memory System
- **Session history**: auto-saved, auto-compacted (summary + hard truncation dual fallback)
- **Long-term memory**: FTS5 trigram full-text search, proactive persistence (Hermes-inspired)
- **Zero external deps**: single SQLite file, survives restarts

### ⏰ Scheduled Tasks
Create tasks in conversation: "Push stock headlines to my QQ every morning at 8 AM". APScheduler + SQLite persistence.

### 📨 Multi-Channel
CLI for dev/debug, QQ Bot (Tencent official API, WebSocket), Email (Gmail SMTP). Share one Agent across all channels.

---

## CLI Commands

| Command | Description |
|---|---|
| `/new [name]` | Start a new session (memory preserved) |
| `/sessions` | List all sessions |
| `/load <name>` | Switch to a session |
| `/delete <name>` | Delete a session |
| `/history [n]` | Show last n messages |
| `/compact` | Force context compaction |
| `/model [name]` | Show / switch model (auto-discovery via API) |
| `/memory` | List all long-term memories |
| `/forget <id>` | Delete a memory by ID |
| `/cron_list` | List all scheduled tasks |
| `/cron_cancel <id>` | Cancel a scheduled task |
| `/help` | Show help |

---

## Config

One `config.toml` controls everything:

```toml
[provider]          # Model provider (OpenAI / DeepSeek / LiteLLM / Ollama etc.)
[agent]             # Agent core settings (max turns, etc.)
[memory]            # Memory system (recall count, compaction threshold, etc.)
[tools]             # Tool security (allowed dirs, shell allowlist/blocklist)
[channels]          # Channel toggles (CLI / QQ / Email)
[scheduler]         # Scheduled tasks
[[mcp.servers]]     # MCP external tools
```

---

## Project Structure

```
minispark/
├── core/               # Agent loop + context assembly
├── providers/          # Model adapter (OpenAI-compatible)
├── tools/
│   ├── function_call/  # 17 built-in FC tools
│   ├── skills/         # Skill loader + built-in skills
│   └── mcp_client.py   # MCP protocol client
├── memory/             # SQLite session + long-term memory
├── channels/           # CLI / QQ / Email channels
├── scheduler.py        # Task scheduler
├── config.py           # Pydantic v2 config validation
└── profile/            # System prompt template
```

---

## Requirements

- Python 3.11+
- < 100MB RAM
- Zero external dependencies

```bash
pip install -e .
```

---

## Docs

[📖 User Manual (Chinese)](docs/用户手册.md)

---

<p align="center">
  <sub>MIT License · Built with ❤️ for 1GB servers</sub>
</p>

---

# 中文

> 这是一个面向低资源环境设计的轻量级 Agent 框架，专注于低内存占用、高可扩展性与深度定制能力。
>
> 项目可在仅有 1GB 内存的服务器上运行。相比常见的 Agent 框架，它尽量减少不必要的依赖与运行开销，同时保留清晰、灵活的模块化结构，便于开发者根据实际需求扩展模型供应商、工具、记忆系统、消息通道和任务调度等功能。
>
> 你既可以将它作为一个轻量、可定制的 Agent 基础框架，用于构建个人助手或自动化服务；也可以将它视为一个便于阅读、调试和学习 Agent 工作原理的教学型项目。

## 为什么是 MiniSpark？

| | 常见 Agent 框架 | MiniSpark |
|---|---|---|
| 内存占用 | 500MB ~ 2GB+ | **< 100MB**（纯 Python，零外部服务） |
| 依赖 | PostgreSQL / Redis / Docker | **仅 SQLite**（单文件） |
| 配置方式 | 环境变量 + YAML + 代码 | **一个 config.toml** |
| 扩展工具 | 写 JSON Schema + 适配器 | **写一个 Python 函数 + 类型注解** |
| 模型切换 | 改环境变量重启 | **/model 一键切换，API 自动发现** |
| 多通道 | 通常仅 CLI | **CLI / QQ / 邮件 三通道复用同一 Agent** |

> **核心理念：** 让 LLM 变成一个能真正干活的小助手，而不是只能聊天。MiniSpark 不做"大而全"，而是把 Agent 循环、工具系统、记忆、定时任务四个核心做到极致，剩下的交给你的 config.toml。

## 架构

```mermaid
flowchart TD
    subgraph CH["📨 Channels"]
        CLI["⌨️ CLI"]  QQ["💬 QQ"]  EM["📧 Email"]
    end
    GW["🚪 Gateway"]
    SCH["⏰ Scheduler"]
    AC[["🧠 Agent Core"]]
    PV["🤖 Provider<br/>OpenAI Compatible"]
    MEM[("🗃️ Memory<br/>SQLite")]
    subgraph TL["🧰 Tools"]
        FC["🔧 Function Call"]  SK["📚 Skills"]  MCP["🔌 MCP"]
    end
    CH --> GW --> AC
    SCH --> AC
    AC --> PV --> LLM["🌐 LLM API / LiteLLM Proxy"]
    AC --> TL
    AC --> MEM
```

## 快速开始

```bash
# 1. 安装
cd MiniSpark
pip install -e .

# 2. 配置 — 只改一个文件
#    在 config.toml 中填入 API Key
[provider]
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key = "sk-your-key"

# 3. 启动
python -m minispark chat
```

```
你: 帮我写一个 Python 脚本，每小时抓一次天气并保存到 weather.csv
MiniSpark: （调用 write_file、schedule_task）✅ 已创建脚本 + 定时任务
```

## 核心特性

### 🧠 Agent 循环
自动请求 LLM → 执行工具 → 回填结果 → 循环，直到任务完成。20 轮熔断 + 上下文溢出自愈 + 上下文自动压缩。

### 🧰 17 个内置工具

| 模块 | 工具 |
|---|---|
| `fs` | `read_file` `write_file` `append_file` `edit_file` `list_dir` |
| `shell` | `run_shell`（黑白名单 + 人工确认） |
| `web` | `web_search` `web_fetch` |
| `memory` | `memory_save` `memory_search` `memory_update` `memory_forget` |
| `schedule` | `schedule_task` `list_tasks` `cancel_task` |
| `email` | `send_email` |
| `skill` | `use_skill`（渐进式披露） |

**新增工具 = 写一个带类型注解的 Python 函数。** 框架自动生成 OpenAI 兼容的 JSON Schema。

### 📚 Skill 技能系统
Skill = 预设的工作流程 prompt。渐进式披露：只注入 name + description，正文按需加载，不浪费 token。内置 `daily-briefing`（每日简报）、`ths-news-hot`（同花顺头条）等。

### 🔌 MCP 协议支持
对接外部 MCP Server，远端工具自动注册为本地工具，与内置 FC 工具统一调度。

### 🗃️ 记忆系统
- **会话历史**：自动保存，超长自动压缩（摘要 + 硬截断双重兜底）
- **长期记忆**：FTS5 trigram 全文检索，主动式持久化（Hermes 理念）
- **零外部依赖**：单文件 SQLite，重启不丢

### ⏰ 定时任务
对话中一句话创建："每天早上 8 点推送同花顺头条到 QQ"。APScheduler 驱动，SQLite 持久化，重启不丢。

### 📨 多通道
CLI（开发调试）、QQ 机器人（腾讯官方 Bot API，WebSocket）、Email（Gmail SMTP）。同一 Agent 复用到所有通道。

## CLI 命令

| 命令 | 说明 |
|---|---|
| `/new [name]` | 新建会话（记忆保留） |
| `/sessions` | 列出所有会话 |
| `/load <name>` | 切换会话 |
| `/delete <name>` | 删除会话 |
| `/history [n]` | 查看最近 n 条消息 |
| `/compact` | 强制压缩上下文 |
| `/model [name]` | 查看/切换模型（API 自动发现可用模型） |
| `/memory` | 查看所有长期记忆 |
| `/forget <id>` | 删除指定记忆 |
| `/cron_list` | 列出所有定时任务 |
| `/cron_cancel <id>` | 取消定时任务 |
| `/help` | 显示帮助 |

## 配置

一个 `config.toml` 控制一切：

```toml
[provider]          # 模型供应商（OpenAI / DeepSeek / LiteLLM / Ollama 等）
[agent]             # Agent 核心参数（最大轮数等）
[memory]            # 记忆系统（召回条数、压缩阈值等）
[tools]             # 工具安全（白名单目录、Shell 黑白名单）
[channels]          # 通道开关（CLI / QQ / Email）
[scheduler]         # 定时任务
[[mcp.servers]]     # MCP 外部工具
```

## 项目结构

```
minispark/
├── core/               # Agent 核心循环 + 上下文组装
├── providers/          # 模型接入（OpenAI 兼容通用接口）
├── tools/
│   ├── function_call/  # 17 个内置 FC 工具
│   ├── skills/         # 技能加载器 + 内置技能
│   └── mcp_client.py   # MCP 协议客户端
├── memory/             # SQLite 会话 + 长期记忆
├── channels/           # CLI / QQ / Email 通道
├── scheduler.py        # 定时任务调度器
├── config.py           # Pydantic v2 配置校验
└── profile/            # System Prompt 模板
```

## 环境要求

- Python 3.11+
- 运行内存 < 100MB
- 零外部服务依赖

```bash
pip install -e .
```

## 文档

[📖 用户手册](docs/用户手册.md)