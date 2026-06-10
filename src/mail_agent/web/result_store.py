"""处理结果持久化存储

JSON 文件存储 ProcessingResult，支持过滤和排序。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mail_agent.config import DATA_DIR
from mail_agent.models import (
    EmailIntent,
    ProcessingResult,
    UrgencyLevel,
)

logger = logging.getLogger(__name__)

DEFAULT_RESULTS_PATH = DATA_DIR / "results.json"


class ResultStore:
    """基于 JSON 的处理结果存储"""

    def __init__(self, path: Path | None = None):
        self._path = path or DEFAULT_RESULTS_PATH
        self._results: list[ProcessingResult] = []
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._results = [ProcessingResult.model_validate(r) for r in data]
            except Exception as e:
                logger.warning("结果数据加载失败: %s", e)
                self._results = []

    def _save(self):
        from mail_agent.io_utils import atomic_write_text

        data = [r.model_dump(mode="json") for r in self._results]
        atomic_write_text(
            self._path,
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
        )

    def add(self, result: ProcessingResult):
        """添加结果（去重：按 message_id）"""
        mid = result.email.message_id
        if mid:
            self._results = [r for r in self._results if r.email.message_id != mid]
        self._results.insert(0, result)
        self._save()

    def add_many(self, results: list[ProcessingResult]):
        for r in results:
            mid = r.email.message_id
            if mid:
                self._results = [
                    x for x in self._results if x.email.message_id != mid
                ]
            self._results.insert(0, r)
        self._save()

    def list_results(
        self,
        *,
        urgency: str | None = None,
        category: str | None = None,
        intent: str | None = None,
        search: str | None = None,
        sort_by: str = "priority",
        order: str = "desc",
    ) -> list[ProcessingResult]:
        """过滤和排序结果"""
        filtered = list(self._results)

        if urgency:
            filtered = [
                r for r in filtered if r.priority.level.value == urgency
            ]
        if category:
            filtered = [
                r for r in filtered if r.analysis.category.value == category
            ]
        if intent:
            filtered = [
                r for r in filtered if r.analysis.intent.value == intent
            ]
        if search:
            q = search.lower()
            filtered = [
                r
                for r in filtered
                if q in r.email.subject.lower()
                or q in r.email.sender.lower()
                or q in r.email.sender_name.lower()
                or q in r.analysis.summary.lower()
            ]

        reverse = order == "desc"
        if sort_by == "date":
            filtered.sort(
                key=lambda r: r.email.date or "",
                reverse=reverse,
            )
        else:
            filtered.sort(
                key=lambda r: r.priority.total_score,
                reverse=reverse,
            )

        return filtered

    def get_urgent(self) -> list[ProcessingResult]:
        """获取 CRITICAL 和 HIGH 优先级的结果"""
        return [
            r
            for r in self._results
            if r.priority.level in (UrgencyLevel.CRITICAL, UrgencyLevel.HIGH)
        ]

    def get_deadlines(self) -> list[ProcessingResult]:
        """获取含截止日期的任务"""
        return [
            r
            for r in self._results
            if r.analysis.intent
            in (EmailIntent.DEADLINE_REMINDER, EmailIntent.TASK_ASSIGNMENT)
            and r.analysis.contains_schedule
        ]

    def clear(self):
        self._results.clear()
        self._save()

    @property
    def count(self) -> int:
        return len(self._results)
