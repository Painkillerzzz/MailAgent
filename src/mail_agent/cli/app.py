"""CLI 命令行界面

基于 Typer + Rich 的交互式命令行工具。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from mail_agent.agent.orchestrator import MailAgent
from mail_agent.calendar.ics_export import export_to_file
from mail_agent.config import load_config
from mail_agent.email.fetcher import IMAPFetcher
from mail_agent.models import (
    EmailMessage,
    ProcessingResult,
    UrgencyLevel,
)

app = typer.Typer(
    name="mail-agent",
    help="基于大模型的智能邮件管理代理",
    no_args_is_help=True,
)
console = Console()


def _urgency_color(level: UrgencyLevel) -> str:
    return {
        UrgencyLevel.CRITICAL: "bold red",
        UrgencyLevel.HIGH: "red",
        UrgencyLevel.MEDIUM: "yellow",
        UrgencyLevel.LOW: "green",
    }.get(level, "white")


def _display_result(result: ProcessingResult, verbose: bool = False):
    """在终端展示处理结果"""
    email = result.email
    analysis = result.analysis
    priority = result.priority

    # 标题面板
    color = _urgency_color(priority.level)
    header = (
        f"[bold]{email.subject}[/bold]\n"
        f"From: {email.sender_name or email.sender} <{email.sender}>\n"
        f"Date: {email.date or 'unknown'}"
    )
    console.print(Panel(header, title=f"[{color}]{priority.level.value.upper()}[/{color}]", border_style=color))

    # 分析结果表
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")
    table.add_row("Intent", analysis.intent.value)
    table.add_row("Urgency", analysis.urgency.value)
    table.add_row("Category", analysis.category.value)
    table.add_row("Requires Reply", str(analysis.requires_reply))
    table.add_row("Priority Score", f"{priority.total_score:.1f}")
    table.add_row("Summary", analysis.summary)
    console.print(table)

    # 日历事件
    if result.calendar_event:
        evt = result.calendar_event
        console.print(
            f"\n  [bold green]Calendar:[/bold green] {evt.title} "
            f"({evt.start_time.strftime('%Y-%m-%d %H:%M')} - "
            f"{evt.end_time.strftime('%H:%M')})"
        )
    if result.schedule_conflict and result.schedule_conflict.has_conflict:
        console.print(
            f"  [bold red]Conflict:[/bold red] "
            f"{len(result.schedule_conflict.conflicting_events)} conflicting event(s)"
        )

    # 回复草稿
    if result.reply_draft:
        console.print(
            Panel(
                result.reply_draft.body,
                title="[bold blue]Reply Draft[/bold blue]",
                border_style="blue",
            )
        )

    # 处理步骤（详细模式）
    if verbose:
        console.print("\n[dim]Processing steps:[/dim]")
        for step in result.processing_steps:
            console.print(f"  [dim]{step}[/dim]")

    console.print()


@app.command()
def demo(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细处理步骤"),
):
    """运行演示：处理预设的示例邮件"""
    console.print("[bold]Mail Agent Demo[/bold]\n", style="blue")

    sample_emails = [
        EmailMessage(
            message_id="<demo-1@mail.com>",
            sender="lee@tsinghua.edu.cn",
            sender_name="Prof. Lee",
            subject="Meeting",
            body=(
                "Hi Xiangyu,\n\n"
                "Can we meet Thursday at 3pm to discuss the results?\n\n"
                "Best,\nLee"
            ),
            date=datetime.now(timezone.utc),
        ),
        EmailMessage(
            message_id="<demo-2@mail.com>",
            sender="john@company.com",
            sender_name="John Smith",
            subject="Please submit the draft by Friday",
            body=(
                "Hi Xiangyu,\n\n"
                "Please make sure to submit the final draft of the report "
                "by this Friday EOD. Let me know if you need more time.\n\n"
                "Thanks,\nJohn"
            ),
            date=datetime.now(timezone.utc),
        ),
        EmailMessage(
            message_id="<demo-3@mail.com>",
            sender="notifications@arxiv.org",
            sender_name="arXiv",
            subject="FYI: Paper accepted at NeurIPS 2026",
            body=(
                "Dear author,\n\n"
                "We are pleased to inform you that your paper "
                "has been accepted at NeurIPS 2026.\n\n"
                "Congratulations!"
            ),
            date=datetime.now(timezone.utc),
        ),
    ]

    agent = MailAgent()
    results = agent.process_emails(sample_emails)

    console.print(f"[bold]Processed {len(results)} emails (sorted by priority):[/bold]\n")
    for result in results:
        _display_result(result, verbose=verbose)


@app.command()
def fetch(
    limit: int = typer.Option(10, "--limit", "-n", help="获取邮件数量上限"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细处理步骤"),
):
    """从 IMAP 邮箱获取并处理未读邮件"""
    config = load_config()

    if not config.imap.host:
        console.print("[red]Error: IMAP 未配置。请在 .env 中设置 IMAP_HOST, IMAP_USERNAME, IMAP_PASSWORD[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Connecting to {config.imap.host}...[/bold]")

    try:
        with IMAPFetcher(config.imap) as fetcher:
            emails = fetcher.fetch_unread(limit=limit)
    except Exception as e:
        console.print(f"[red]连接邮箱失败: {e}[/red]")
        raise typer.Exit(1)

    if not emails:
        console.print("[yellow]没有未读邮件[/yellow]")
        return

    console.print(f"[bold]获取到 {len(emails)} 封未读邮件，开始处理...[/bold]\n")

    agent = MailAgent(config)
    results = agent.process_emails(emails)

    for result in results:
        _display_result(result, verbose=verbose)


@app.command()
def calendar(
    days: int = typer.Option(7, "--days", "-d", help="查看未来几天的日程"),
    export: str = typer.Option(None, "--export", "-e", help="导出为 .ics 文件"),
):
    """查看日历事件"""
    config = load_config()
    from mail_agent.calendar.store import CalendarStore

    store = CalendarStore(config.calendar)
    now = datetime.now()
    events = store.list_events(
        start=now,
        end=now + timedelta(days=days),
    )

    if not events:
        console.print("[yellow]未来 {} 天没有日程安排[/yellow]".format(days))
        return

    table = Table(title=f"未来 {days} 天日程")
    table.add_column("时间", style="cyan")
    table.add_column("标题", style="bold")
    table.add_column("参与者")
    table.add_column("来源")

    for evt in events:
        table.add_row(
            f"{evt.start_time.strftime('%m-%d %H:%M')} - {evt.end_time.strftime('%H:%M')}",
            evt.title,
            ", ".join(evt.attendees),
            evt.source_email_id or "-",
        )

    console.print(table)

    if export:
        path = export_to_file(events, export)
        console.print(f"\n[green]已导出到 {path}[/green]")


@app.command()
def analyze(
    sender: str = typer.Option(..., "--from", "-f", help="发件人邮箱"),
    subject: str = typer.Option(..., "--subject", "-s", help="邮件主题"),
    body: str = typer.Option(..., "--body", "-b", help="邮件正文"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """分析单封邮件"""
    email_msg = EmailMessage(
        sender=sender,
        subject=subject,
        body=body,
        date=datetime.now(timezone.utc),
    )

    agent = MailAgent()
    result = agent.process_email(email_msg)
    _display_result(result, verbose=verbose)


@app.command()
def summary(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="使用LLM生成详细简报"),
):
    """生成邮件处理摘要"""
    from mail_agent.web.result_store import ResultStore
    from mail_agent.understanding.summarizer import EmailSummarizer

    store = ResultStore()
    results = store.list_results()

    if not results:
        console.print("[yellow]没有已处理的邮件。请先运行 demo 或 fetch。[/yellow]")
        return

    summarizer = EmailSummarizer()
    stats = summarizer.generate_stats(results)

    # 统计表
    table = Table(title="Email Summary")
    table.add_column("Metric", style="bold cyan")
    table.add_column("Count", justify="right")
    table.add_row("Total Emails", str(stats["total"]))
    table.add_row("Needs Reply", str(stats["needs_reply"]))
    table.add_row("Meetings", str(stats["meetings"]))
    table.add_row("Tasks/Deadlines", str(stats["tasks"]))
    table.add_row("Urgent", str(stats["urgent"]))
    console.print(table)

    # 分类统计
    if stats["by_category"]:
        cat_table = Table(title="By Category")
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Count", justify="right")
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            cat_table.add_row(cat, str(count))
        console.print(cat_table)

    # LLM 简报
    if verbose:
        console.print("\n[bold]Generating AI briefing...[/bold]")
        config = load_config()
        from mail_agent.llm.client import LLMClient

        llm = LLMClient(config.llm)
        summarizer_llm = EmailSummarizer(llm)
        briefing = summarizer_llm.generate_briefing(results)
        console.print(Panel(briefing, title="[bold blue]AI Briefing[/bold blue]", border_style="blue"))


@app.command()
def web(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="监听地址"),
    port: int = typer.Option(8000, "--port", "-p", help="监听端口"),
):
    """启动 Web 仪表板"""
    console.print(f"[bold]Starting web dashboard at http://{host}:{port}[/bold]")
    from mail_agent.web.app import run_server

    run_server(host=host, port=port)


if __name__ == "__main__":
    app()
