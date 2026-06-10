# Mail Agent - 智能邮件管理代理

基于大模型（智谱AI GLM-4.6）的邮件管理代理系统，自动理解邮件内容，实现智能分类、优先级判断、日历调度和个性化回复生成。

## 核心功能

- **邮件语义理解**：利用 LLM 分析邮件意图（会议请求/任务分配/通知等）、紧急程度
- **智能分类**：基于语义进行邮件分类，而非简单关键词匹配
- **优先级评分**：结合规则（发件人权重、截止日期）和 LLM 分析的综合评分
- **日历自动调度**：解析时间信息、检测冲突、自动创建日历事件、支持 ICS 导出
- **个性化回复**：根据邮件内容、用户风格生成自然的回复草稿
- **Google 生态原生对接**：通过 Gmail API + Google Calendar API（OAuth2）读取真实未读邮件、在 **真实 Google Calendar** 创建日程、把回复存为 Gmail 草稿或直接发送、标记已读

## 系统架构

```
Gmail API / IMAP → Email Fetcher → Email Parser → LLM Analysis → Intent Routing
                                                                      │
                                         ┌────────────────────────────┤
                                         │              │             │
                                  Calendar Scheduler  Reply Generator  Mark Read
                                         │              │
                              Google Calendar 事件   Gmail 草稿 / 发送
```

## 快速开始

### 环境要求

- Python >= 3.12
- [uv](https://github.com/astral-sh/uv) 包管理器

### 安装

```bash
git clone https://github.com/your-username/MailAgent.git
cd MailAgent
cp .env.example .env
# 编辑 .env 填入你的智谱AI API Key
uv sync
```

### 使用

#### 运行演示（推荐首次使用）

```bash
uv run mail-agent demo
```

处理 3 封预设示例邮件，展示完整的分析→评分→调度→回复流程。

#### 分析单封邮件

```bash
uv run mail-agent analyze \
  --from "prof@university.edu" \
  --subject "Meeting Request" \
  --body "Can we meet Thursday at 3pm to discuss the paper?"
```

#### 对接真实 Gmail + Google Calendar（推荐）

按 [Google 生态配置](#google-生态配置gmail--calendar) 完成 OAuth 授权后：

```bash
# 首次：浏览器授权一次（会生成 data/token.json）
uv run mail-agent auth

# 拉取真实未读邮件 → 分析 → 在 Google Calendar 建日程 → 回复存为 Gmail 草稿
uv run mail-agent fetch --limit 10

# 直接发送回复（默认仅存草稿）
uv run mail-agent fetch --send

# 处理后把邮件标记为已读
uv run mail-agent fetch --mark-read
```

#### 从邮箱获取并处理未读邮件（IMAP 备选方案）

```bash
# 在 .env 中配置 IMAP 信息（GOOGLE_ENABLED=false 时生效）
uv run mail-agent fetch --limit 10
```

#### 读写回读自验证（推荐在真实环境首次使用后运行）

```bash
# 对真实 Gmail/Calendar 跑「写入→回读→校验→清理」闭环
uv run mail-agent selfcheck
# 额外验证发送链路（会向测试邮箱发一封测试邮件）
uv run mail-agent selfcheck --send
# 保留创建出的事件/草稿（默认自动清理）
uv run mail-agent selfcheck --no-cleanup
```

`selfcheck` 会创建临时日历事件/草稿，立刻读回校验字段一致后删除，确保读写操作正确。

#### 测试模式（避免误发给真实联系人）

`fetch` 加 `--test` 后，所有外发回复改投到测试邮箱（默认 `TEST_REDIRECT_TO`），
并在主题/正文标注真实目标收件人：

```bash
uv run mail-agent fetch --test            # 回复改投测试邮箱并存草稿
uv run mail-agent fetch --test --send     # 真实发送到测试邮箱
uv run mail-agent fetch --test-to a@b.com # 临时指定重定向邮箱
```

#### 查看日历事件

```bash
uv run mail-agent calendar --days 7
# 导出为 ICS 文件
uv run mail-agent calendar --export events.ics
```

#### 启动 Web 仪表板

```bash
uv run mail-agent web --port 8000
```

访问 `http://localhost:8000` 查看仪表板。

## Google 生态配置（Gmail + Calendar）

让 Agent 真正读写你的 Gmail 和 Google Calendar，需要一次性的 OAuth2 配置：

1. **创建 Google Cloud 项目**
   打开 [Google Cloud Console](https://console.cloud.google.com/) → 新建项目。

2. **启用 API**
   在「API 和服务 → 库」中分别启用 **Gmail API** 和 **Google Calendar API**。

3. **配置 OAuth 同意屏幕**
   「API 和服务 → OAuth 同意屏幕」→ 选择「外部」→ 填写应用名等基本信息 →
   在「测试用户」中加入你自己的 Gmail（如 `painkillerjz40@gmail.com`），这样无需通过 Google 审核即可使用。

4. **创建 OAuth 客户端凭据**
   「API 和服务 → 凭据 → 创建凭据 → OAuth 客户端 ID」→ 应用类型选 **桌面应用** →
   下载 JSON，重命名为 `credentials.json` 放到项目根目录。

5. **配置 `.env`**
   ```bash
   GOOGLE_ENABLED=true
   GOOGLE_CREDENTIALS=credentials.json
   GOOGLE_CALENDAR_ID=primary
   ```
   > `credentials.json` 必须是 Google Cloud 下载的**完整 JSON**（含 `client_id` 和 `client_secret`），
   > 不能只粘贴一行 client ID。也可以不放文件，改在 `.env` 设置
   > `GOOGLE_CLIENT_ID` 和 `GOOGLE_CLIENT_SECRET` 二者。

6. **完成授权**
   ```bash
   uv run mail-agent auth
   ```
   浏览器会弹出 Google 授权页，同意后 token 会缓存到 `data/token.json`，之后自动刷新，无需重复授权。

> 授权范围：`gmail.modify`（读/标签/草稿）+ `gmail.send`（发送）+ `calendar`（日历读写）。
> `credentials.json` 和 `token.json` 已加入 `.gitignore`，请勿提交到仓库。

完成后，`fetch` / `calendar` 命令及 Web 仪表板会自动切换到真实的 Gmail 与 Google Calendar。

## 项目结构

```
src/mail_agent/
├── config.py              # 配置管理
├── models.py              # 数据模型 (Pydantic)
├── llm/client.py          # 智谱AI LLM 客户端
├── email/
│   ├── fetcher.py         # IMAP 邮件获取
│   └── parser.py          # 邮件解析
├── gapi/                  # Google 生态集成
│   ├── auth.py            # OAuth2 授权
│   ├── gmail.py           # Gmail API（读/发/草稿/标签）
│   └── gcalendar.py       # Google Calendar API
├── understanding/
│   ├── analyzer.py        # LLM 语义分析
│   └── priority.py        # 优先级评分
├── calendar/
│   ├── store.py           # 本地日历存储
│   ├── scheduler.py       # 日历调度
│   └── ics_export.py      # ICS 导出
├── reply/generator.py     # 回复生成
├── agent/orchestrator.py  # Agent 编排器
├── cli/app.py             # CLI 界面
└── web/app.py             # Web 仪表板
```

## 测试

```bash
# 运行全部测试（包含真实 API 集成测试）
uv run pytest tests/ -v

# 运行带覆盖率
uv run pytest tests/ --cov=mail_agent --cov-report=term-missing
```

## 技术栈

- **LLM**: 智谱AI GLM-4.6（支持 GLM Coding Plan 专属端点）
- **数据模型**: Pydantic v2
- **CLI**: Typer + Rich
- **Web**: FastAPI + Jinja2
- **Google**: Gmail API + Google Calendar API (google-api-python-client, OAuth2)
- **日历**: Google Calendar / icalendar (ICS 导出)
- **邮件**: Gmail API / Python imaplib (IMAP 协议)
- **测试**: pytest

## License

MIT
