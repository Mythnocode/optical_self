from __future__ import annotations

from collections import Counter

from .schemas import (
    AnswerFinding,
    AssistantAnswer,
    DiagnosticFinding,
    HelpContext,
    QuestionType,
    SearchHit,
)


def classify_question(question: str) -> QuestionType:
    text = question.strip().lower()
    if any(word in text for word in ("在哪里", "在哪", "打开", "进入哪个页面", "怎么进入", "入口")):
        return "navigation"
    if any(word in text for word in ("报错", "错误", "失败", "无法", "不收敛", "异常", "卡住")):
        return "troubleshooting"
    if "为什么" in text and any(word in text for word in ("效率", "结果", "预测", "耦合", "光斑", "模型", "焦面", "收敛")):
        return "diagnosis"
    if any(
        phrase in text
        for phrase in (
            "为什么我的",
            "为什么当前",
            "为什么这个结果",
            "为什么结果",
            "为什么模型",
            "为什么预测",
            "结果很低",
            "结果偏低",
            "效率很低",
            "为什么低",
            "为什么不对",
        )
    ):
        return "diagnosis"
    if any(word in text for word in ("怎么", "如何", "步骤", "怎样", "操作", "设置")):
        return "how_to"
    return "definition"


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _knowledge_findings(hits: list[SearchHit], limit: int) -> list[AnswerFinding]:
    findings: list[AnswerFinding] = []
    for hit in hits[:limit]:
        findings.append(
            AnswerFinding(
                title=hit.title,
                explanation=hit.summary,
                source_ids=[hit.id],
                action_ids=hit.action_ids,
                kind="knowledge",
            )
        )
    return findings


def compose_answer(
    question: str,
    *,
    context: HelpContext,
    hits: list[SearchHit],
    diagnostic_findings: list[DiagnosticFinding],
) -> AssistantAnswer:
    question_type = classify_question(question)
    findings: list[AnswerFinding] = []
    warnings: list[str] = []
    used_current_result = False

    if question_type in {"diagnosis", "troubleshooting"} and diagnostic_findings:
        for item in diagnostic_findings[:4]:
            findings.append(
                AnswerFinding(
                    title=item.title,
                    explanation=item.explanation,
                    source_ids=item.source_ids,
                    action_ids=item.action_ids,
                    kind="diagnostic" if item.severity != "critical" else "warning",
                    evidence_paths=item.evidence_paths,
                )
            )
        used_current_result = context.has_current_result

    remaining = max(0, 4 - len(findings))
    if remaining:
        knowledge_limit = remaining if question_type != "diagnosis" else min(remaining, 2)
        ordered_hits = hits
        if question_type in {"diagnosis", "troubleshooting"}:
            type_priority = {"diagnostic": 0, "guide": 1, "parameter": 2, "principle": 3, "faq": 4}
            ordered_hits = sorted(
                hits,
                key=lambda item: (type_priority.get(item.entry_type, 9), -item.final_score),
            )
        findings.extend(_knowledge_findings(ordered_hits, knowledge_limit))

    
    
    summary = ""
    if question_type == "diagnosis":
        if context.has_current_result and not diagnostic_findings:
            summary = "当前结果未触发已配置的确定性诊断规则，不能据此认定具体损失原因。"
            warnings.append("未发现足够的当前结果证据来确定单一主因。")
        elif not context.has_current_result:
            summary = "未读取到当前正式分析结果，不能判断本项目的具体原因。"
            warnings.append("未读取到当前正式结果，不能判断本项目的具体原因。")

    if not findings:
        return AssistantAnswer(
            question_type=question_type,
            status="insufficient",
            summary="当前知识库没有足够证据回答这个问题。",
            findings=[],
            source_ids=[],
            action_ids=[],
            confidence="low",
            used_current_result=False,
            warnings=["请补充更具体的参数名、错误信息或正式结果。"],
        )

    source_ids = _dedupe([source for item in findings for source in item.source_ids])
    action_ids = _dedupe([action for item in findings for action in item.action_ids])[:3]

    if diagnostic_findings and context.has_current_result:
        confidence = "high" if len(diagnostic_findings) >= 2 else "medium"
        status = "supported"
    elif hits and hits[0].final_score >= 0.35:
        confidence = "medium"
        status = "supported" if question_type != "diagnosis" else "partial"
    else:
        confidence = "low"
        status = "partial"

    return AssistantAnswer(
        question_type=question_type,
        status=status,
        summary=summary,
        findings=findings,
        source_ids=source_ids,
        action_ids=action_ids,
        confidence=confidence,
        used_current_result=used_current_result,
        warnings=warnings,
    )
