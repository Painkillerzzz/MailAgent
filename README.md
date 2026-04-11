# Mail Agent - 智能邮件管理代理

基于大模型（智谱AI GLM-5）的邮件管理代理系统，自动理解邮件内容，实现智能分类、优先级判断、日历调度和个性化回复生成。

## 核心功能

- **邮件语义理解**：利用 LLM 分析邮件意图（会议请求/任务分配/通知等）、紧急程度
- **智能分类**：基于语义进行邮件分类，而非简单关键词匹配
- **优先级评分**：结合规则（发件人权重、截止日期）和 LLM 分析的综合评分
- **日历自动调度**：解析时间信息、检测冲突、自动创建日历事件、支持 ICS 导出
- **个性化回复**：根据邮件内容、用户风格生成自然的回复草稿

## 系统架构

```
Email Server (IMAP) → Email Fetcher → Email Parser → LLM Analysis → Intent Routing
                                                                         │
                                            ┌────────────────────────────┤
                                            │            │               │
                                     Calendar Scheduler  Reply Generator  Smart Labels
                                            │            │
                                     Event Created    Reply Draft
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

#### 从邮箱获取并处理未读邮件

```bash
# 需要先在 .env 中配置 IMAP 信息
uv run mail-agent fetch --limit 10
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

## 项目结构

```
src/mail_agent/
├── config.py              # 配置管理
├── models.py              # 数据模型 (Pydantic)
├── llm/client.py          # 智谱AI LLM 客户端
├── email/
│   ├── fetcher.py         # IMAP 邮件获取
│   └── parser.py          # 邮件解析
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

- **LLM**: 智谱AI GLM-5
- **数据模型**: Pydantic v2
- **CLI**: Typer + Rich
- **Web**: FastAPI + Jinja2
- **日历**: icalendar (ICS 导出)
- **邮件**: Python imaplib (IMAP 协议)
- **测试**: pytest

## License

MIT
