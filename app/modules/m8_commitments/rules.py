from app.reasons import reject
from app.errors import DomainError
from app.values import instant


def evaluate(rows, context):
    """承诺账本审计：纯校验 + 可追溯视图，不重新裁决、不产生新赔付。

    账本在 M4 路径裁决阶段按事件时刻一次性构建，本阶段只做不变量校验：
    - 每票必须且仅有一条追加式版本链；
    - 版本区间半开且首尾相接、无断层；旧版本只关闭不删除；
    - 每次扫描可追到其发生时刻有效的承诺版本。
    重跑同一输入恒得同一结果（纯函数），不会新增版本或重复计赔。
    """
    good = []
    bad = []
    for row in rows:
        ledger = row.get("commitment_ledger")
        if not ledger:
            bad.append(reject(row, "LEDGER_MISSING", "包裹缺少承诺账本"))
            continue
        cursor = None
        for index, version in enumerate(ledger):
            if index == 0 and version["version"] != "v0":
                bad.append(reject(row, "LEDGER_GAP", "首版本必须是收件锁定的v0"))
            if index > 0 and instant(version["effective_from"]) != cursor:
                bad.append(reject(row, "LEDGER_GAP", f"承诺版本{version['version']}区间断层"))
            cursor = None if version["effective_to"] is None else instant(version["effective_to"])
        if ledger[-1]["effective_to"] is not None:
            bad.append(reject(row, "LEDGER_GAP", "末版本必须保持生效中"))
        stamps = row.get("scans", [])
        good.append({
            "parcel": row["parcel"],
            "accepted_at": row["accepted_at"],
            "delivered_at": row.get("delivered_at"),
            "commitment_versions": len(ledger),
            "active_commitment_version": row.get("active_commitment_version", ledger[-1]["version"]),
            "promised_hours": row.get("promised_hours", ledger[-1]["promised_hours"]),
            "sla": row.get("sla"),
            "expected": row.get("expected"),
            "amendment_count": row.get("amendment_count", 0),
            "amendment_rejected": row.get("amendment_rejected", 0),
            "scans": stamps,
            "commitment_ledger": ledger,
        })
    metrics = {
        "parcels": len(good),
        "ledger_versions": sum(r["commitment_versions"] for r in good),
        "amended_parcels": sum(r["commitment_versions"] > 1 for r in good),
        "amendments_rejected": sum(r["amendment_rejected"] for r in good),
        "ledger_breaks": len(bad),
        "stamped_scans": sum(len(r["scans"]) for r in good),
    }
    if bad:
        raise DomainError("LEDGER_GAP", "承诺账本不变量校验失败，不能归档")
    return {"rows": good, "quarantine": [], "metrics": metrics}
