from app.values import instant

# 承诺改约确认节点：客户在该时点确认更紧/更松的新承诺。
# 裁决规则：新承诺自【确认时点】(event_utc) 生效，不追溯生效之前的结论；
# 补传的上传时刻(received_utc)只用于上传延迟统计，不改变生效时点。
AMEND_NODE = "AMEND"

# 改约失败原因
AMEND_FAILED = "AMEND_FAILED"            # 上游明确标记改约失败（保留上一可用结论）
AMEND_BEFORE_ACCEPT = "AMEND_BEFORE_ACCEPT"  # 确认时点早于该票最早收件
AMEND_AFTER_DELIVERY = "AMEND_AFTER_DELIVERY"  # 确认时点晚于妥投，结论已锁
AMEND_CONFLICT = "AMEND_CONFLICT"        # 同一确认时点出现互斥新承诺
AMEND_REASON_DETAIL = {
    AMEND_FAILED: "改约失败，保留上一可用承诺",
    AMEND_BEFORE_ACCEPT: "确认时点早于收件，改约无效",
    AMEND_AFTER_DELIVERY: "确认时点晚于妥投，承诺已锁定",
    AMEND_CONFLICT: "同一确认时点承诺冲突，保留先到版本",
}


def version_at(ledger, moment):
    """按发生时刻取当时有效承诺版本（半开区间 [effective_from, next)）。

    ledger 为追加式版本链，按 effective_from 升序。任何时刻都能落到
    某一版本；moment 早于首个版本时回退 V0（理论上不会发生）。
    """
    when = instant(moment)
    chosen = ledger[0]
    for version in ledger:
        if instant(version["effective_from"]) <= when:
            chosen = version
        else:
            break
    return chosen


def build_ledger(accepted_at, delivered_at, initial_promised, initial_sources, amendments):
    """为单票构建追加式承诺版本链，并裁决每次改约是否成立。

    返回 (ledger, rejected)：
    - ledger：V0 锁自最早有效收件扫描携带的承诺；成功改约只追加新版本，
      旧版本仅关闭区间、绝不删除或覆盖。
    - rejected：失败/无效改约的隔离记录，原始字段完整保留。
    纯函数：相同输入恒得相同输出，重跑不产生新版本、不重复计赔。
    """
    accept = instant(accepted_at)
    delivery = instant(delivered_at) if delivered_at else None
    ordered = sorted(amendments, key=lambda a: (instant(a["event_utc"]), a["scan_id"]))
    ledger = [{
        "version": "v0",
        "promised_hours": str(initial_promised),
        "effective_from": accept.isoformat(),
        "effective_to": None,
        "source_lines": list(initial_sources),
        "basis": "最早有效收件扫描锁定",
        "status": "生效中",
    }]
    rejected = []
    seen_moments = set()
    for amendment in ordered:
        at = instant(amendment["event_utc"])
        reason = None
        if str(amendment.get("amend_failed", "")).strip().lower() in {"1", "true", "yes", "y", "失败"}:
            reason = AMEND_FAILED
        elif at < accept:
            reason = AMEND_BEFORE_ACCEPT
        elif delivery is not None and at > delivery:
            reason = AMEND_AFTER_DELIVERY
        elif at in seen_moments:
            reason = AMEND_CONFLICT
        if reason is not None:
            rejected.append({
                **amendment,
                "reason": reason,
                "detail": AMEND_REASON_DETAIL[reason],
                "rejected_version": ledger[-1]["version"],
            })
            continue
        seen_moments.add(at)
        index = len(ledger)
        previous = ledger[-1]
        previous["effective_to"] = at.isoformat()
        previous["status"] = "已关闭"
        ledger.append({
            "version": f"v{index}",
            "promised_hours": amendment["promised_hours"],
            "effective_from": at.isoformat(),
            "effective_to": None,
            "source_lines": list(amendment.get("_sources", [])),
            "basis": "客户确认改约，自确认时点生效",
            "status": "生效中",
        })
    return ledger, rejected


def stamp_scan(ledger, scan):
    """让每次扫描/改约事件可追溯到其发生时刻有效的承诺版本。"""
    version = version_at(ledger, scan["event_utc"])
    return {
        "scan_id": scan["scan_id"],
        "event_utc": scan["event_utc"],
        "node": scan["node"],
        "carried_promised_hours": scan.get("promised_hours"),
        "commitment_version": version["version"],
        "effective_promised_hours": version["promised_hours"],
        "source_lines": list(scan.get("_sources", [])),
    }
