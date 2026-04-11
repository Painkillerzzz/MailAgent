"""邮件优先级评分模块

结合规则和 LLM 分析结果进行优先级评分。
"""

from __future__ import annotations

from mail_agent.models import (
    EmailAnalysis,
    EmailCategory,
    EmailIntent,
    EmailMessage,
    PriorityScore,
    UrgencyLevel,
)

# 发件人权重映射（可配置的 VIP 列表）
DEFAULT_VIP_DOMAINS = ["tsinghua.edu.cn", "pku.edu.cn"]
DEFAULT_VIP_KEYWORDS = ["prof", "professor", "director", "dean", "boss", "manager"]

# 意图权重映射
INTENT_WEIGHTS: dict[EmailIntent, float] = {
    EmailIntent.MEETING_REQUEST: 3.0,
    EmailIntent.TASK_ASSIGNMENT: 3.5,
    EmailIntent.DEADLINE_REMINDER: 4.0,
    EmailIntent.COOPERATION_REQUEST: 2.5,
    EmailIntent.INQUIRY: 2.0,
    EmailIntent.REPLY_EXPECTED: 2.5,
    EmailIntent.INFORMATION_SHARING: 1.0,
    EmailIntent.NOTIFICATION: 0.5,
    EmailIntent.SOCIAL: 0.5,
    EmailIntent.OTHER: 0.5,
}

# 紧急度权重映射
URGENCY_WEIGHTS: dict[UrgencyLevel, float] = {
    UrgencyLevel.CRITICAL: 5.0,
    UrgencyLevel.HIGH: 3.5,
    UrgencyLevel.MEDIUM: 2.0,
    UrgencyLevel.LOW: 0.5,
}


def _compute_sender_weight(
    email_msg: EmailMessage,
    vip_domains: list[str] | None = None,
    vip_keywords: list[str] | None = None,
) -> float:
    """计算发件人权重"""
    if vip_domains is None:
        vip_domains = DEFAULT_VIP_DOMAINS
    if vip_keywords is None:
        vip_keywords = DEFAULT_VIP_KEYWORDS

    score = 0.0
    sender_lower = email_msg.sender.lower()
    name_lower = email_msg.sender_name.lower()

    # VIP 域名检查
    for domain in vip_domains:
        if domain in sender_lower:
            score += 2.0
            break

    # VIP 关键词检查（发件人名称）
    for keyword in vip_keywords:
        if keyword in name_lower:
            score += 1.5
            break

    return score


def _compute_deadline_weight(analysis: EmailAnalysis) -> float:
    """计算截止日期权重"""
    score = 0.0
    if analysis.contains_schedule:
        score += 1.5
    if analysis.intent == EmailIntent.DEADLINE_REMINDER:
        score += 2.0
    # 检查关键词中是否有截止日期相关
    deadline_keywords = ["deadline", "due", "by", "before", "urgent", "asap"]
    for point in analysis.key_points:
        if any(kw in point.lower() for kw in deadline_keywords):
            score += 1.0
            break
    return score


def _score_to_level(total: float) -> UrgencyLevel:
    """将总分映射为紧急等级"""
    if total >= 10.0:
        return UrgencyLevel.CRITICAL
    elif total >= 7.0:
        return UrgencyLevel.HIGH
    elif total >= 4.0:
        return UrgencyLevel.MEDIUM
    else:
        return UrgencyLevel.LOW


class PriorityScorer:
    """邮件优先级评分器"""

    def __init__(
        self,
        vip_domains: list[str] | None = None,
        vip_keywords: list[str] | None = None,
    ):
        self._vip_domains = vip_domains or DEFAULT_VIP_DOMAINS
        self._vip_keywords = vip_keywords or DEFAULT_VIP_KEYWORDS

    def score(
        self, email_msg: EmailMessage, analysis: EmailAnalysis
    ) -> PriorityScore:
        """计算邮件优先级评分

        Args:
            email_msg: 邮件消息
            analysis: LLM 分析结果

        Returns:
            PriorityScore 评分结果
        """
        sender_w = _compute_sender_weight(
            email_msg, self._vip_domains, self._vip_keywords
        )
        deadline_w = _compute_deadline_weight(analysis)
        intent_w = INTENT_WEIGHTS.get(analysis.intent, 0.5)
        urgency_w = URGENCY_WEIGHTS.get(analysis.urgency, 0.5)

        total = sender_w + deadline_w + intent_w + urgency_w

        reasons = []
        if sender_w > 0:
            reasons.append(f"VIP sender (+{sender_w:.1f})")
        if deadline_w > 0:
            reasons.append(f"deadline related (+{deadline_w:.1f})")
        reasons.append(f"intent={analysis.intent.value} (+{intent_w:.1f})")
        reasons.append(f"urgency={analysis.urgency.value} (+{urgency_w:.1f})")

        return PriorityScore(
            sender_weight=sender_w,
            deadline_weight=deadline_w,
            intent_weight=intent_w,
            urgency_weight=urgency_w,
            total_score=total,
            level=_score_to_level(total),
            reasoning="; ".join(reasons),
        )
