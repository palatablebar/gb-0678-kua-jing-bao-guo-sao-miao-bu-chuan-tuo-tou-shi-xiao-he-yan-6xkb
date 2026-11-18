from app.pipeline import calculate, execute, load_sample
from app import store
from app.commitments.ledger import build_ledger, version_at, stamp_scan, AMEND_NODE
from app.modules.m4_paths.rules import evaluate as paths
from app.modules.m8_commitments.rules import evaluate as commitments
from app.values import instant
from decimal import Decimal
import pytest


def amend(scan_id, at, hours, failed=False):
    return {"scan_id": scan_id, "parcel": "P1", "node": AMEND_NODE, "event_utc": at,
            "received_utc": "2026-11-05T00:00:00Z", "zone": "Asia/Tokyo", "destination": "JP",
            "promised_hours": str(hours), "declared_value": "200", "reported": "0",
            "amend_failed": failed, "_sources": [int(scan_id)]}


def physical(scan_id, node, at, hours=24):
    return {"scan_id": scan_id, "parcel": "P1", "node": node, "event_utc": at,
            "received_utc": "2026-11-05T00:00:00Z", "zone": "Asia/Tokyo", "destination": "JP",
            "promised_hours": str(hours), "declared_value": "200", "reported": "0", "_sources": [int(scan_id)]}


# 裁决一：新承诺自客户确认时点生效，而非补传上传/扫描发生时间
def test_new_commitment_effective_at_confirmation_not_upload():
    ledger, rejected = build_ledger(
        "2026-11-02T00:00:00Z", "2026-11-04T00:00:00Z", "24", [1],
        [{"scan_id": "9", "event_utc": "2026-11-02T06:00:00Z", "received_utc": "2026-11-02T15:00:00Z",
          "promised_hours": "12", "amend_failed": False, "_sources": [9]}])
    assert rejected == []
    assert ledger[0]["effective_to"] == "2026-11-02T06:00:00+00:00"
    assert ledger[1]["effective_from"] == "2026-11-02T06:00:00+00:00"
    # 确认前一刻仍用旧承诺，确认后立即用新承诺，与15:00补传上传时刻无关
    assert version_at(ledger, "2026-11-02T05:59:00Z")["version"] == "v0"
    assert version_at(ledger, "2026-11-02T06:00:00Z")["promised_hours"] == "12"


# 裁决二：生效前后的扫描各用当时承诺，扫描行自带新旧时限不改账
def test_scans_before_and_after_use_then_current_promise():
    ledger, _ = build_ledger(
        "2026-11-02T00:00:00Z", "2026-11-04T00:00:00Z", "24", [1],
        [amend("9", "2026-11-02T06:00:00Z", 12)])
    before = stamp_scan(ledger, physical("2", "DEPART", "2026-11-02T03:00:00Z", hours=24))
    after = stamp_scan(ledger, physical("3", "CUSTOMS", "2026-11-03T00:00:00Z", hours=12))
    assert (before["commitment_version"], before["effective_promised_hours"]) == ("v0", "24")
    assert (after["commitment_version"], after["effective_promised_hours"]) == ("v1", "12")
    # 扫描自带值仅留痕，不参与落钉结论
    assert after["carried_promised_hours"] == "12"


# 裁决三：改约失败保留上一可用结论，旧承诺依据不删除不覆盖
def test_failed_amendment_keeps_previous_commitment_intact():
    ledger, rejected = build_ledger(
        "2026-11-02T00:00:00Z", "2026-11-04T00:00:00Z", "24", [1],
        [amend("8", "2026-11-02T18:00:00Z", 12, failed=True)])
    assert len(ledger) == 1 and ledger[0]["version"] == "v0"
    assert ledger[0]["effective_to"] is None and ledger[0]["status"] == "生效中"
    assert rejected[0]["reason"] == "AMEND_FAILED" and rejected[0]["rejected_version"] == "v0"
    # 原始失败依据完整保留，可恢复
    assert rejected[0]["promised_hours"] == "12" and rejected[0]["_sources"] == [8]


def test_amendment_after_delivery_cannot_reopen_locked_conclusion():
    ledger, rejected = build_ledger(
        "2026-11-02T00:00:00Z", "2026-11-04T00:00:00Z", "24", [1],
        [amend("8", "2026-11-05T12:00:00Z", 12)])
    assert len(ledger) == 1
    assert rejected[0]["reason"] == "AMEND_AFTER_DELIVERY"


def test_amendment_before_accept_is_rejected():
    ledger, rejected = build_ledger(
        "2026-11-02T00:00:00Z", None, "24", [1],
        [amend("8", "2026-11-01T20:00:00Z", 12)])
    assert len(ledger) == 1
    assert rejected[0]["reason"] == "AMEND_BEFORE_ACCEPT"


def test_same_moment_conflicting_amendments_keep_first():
    ledger, rejected = build_ledger(
        "2026-11-02T00:00:00Z", "2026-11-05T00:00:00Z", "24", [1],
        [amend("33", "2026-11-03T06:00:00Z", 12), amend("34", "2026-11-03T06:00:00Z", 10)])
    assert [v["version"] for v in ledger] == ["v0", "v1"]
    assert ledger[1]["promised_hours"] == "12"
    assert rejected[0]["reason"] == "AMEND_CONFLICT" and rejected[0]["rejected_version"] == "v1"


# 裁决四：每票唯一承诺链与唯一赔付结论，分段计时不追溯
def test_each_parcel_has_single_ledger_and_single_compensation():
    rows = paths([
        physical("1", "ACCEPT", "2026-11-02T00:00:00Z"),
        physical("2", "DEPART", "2026-11-02T12:00:00Z"),
        amend("9", "2026-11-02T06:00:00Z", 12),
        physical("3", "DELIVERED", "2026-11-04T00:00:00Z", 12),
    ], {})["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert [v["version"] for v in row["commitment_ledger"]] == ["v0", "v1"]
    view = commitments(rows, {})
    assert len(view["rows"]) == 1 and view["metrics"]["ledger_breaks"] == 0


def test_segmented_clock_does_not_retroactively_rejudge_early_segment():
    result = calculate(load_sample("amendments.csv"), stop=5)
    a001 = next(r for r in result["stages"][4]["rows"] if r["parcel"] == "A001")
    segments = {s["version"]: s for s in a001["commitment_segments"]}
    # 生效前段仍按24h裁决（6个工作小时，不超时）；生效后段按12h独立计时
    assert segments["v0"]["working_hours"] == "6.0" and segments["v0"]["late_hours"] == "0"
    assert segments["v1"]["working_hours"] == "18.0" and segments["v1"]["late_hours"] == "6.0"
    # 每票唯一结论
    assert a001["sla"] == "超时" and a001["expected"] == "6.00"
    assert a001["active_commitment_version"] == "v1"


# 裁决五：同一版本重跑不新增、不重复计赔
def test_rerun_same_input_is_idempotent_no_double_compensation(tmp_path):
    raw = load_sample("amendments.csv")
    first = execute(raw)
    second = execute(raw)
    assert first["run_id"] == second["run_id"]
    assert len(store.history()) == 1
    total_1 = first["stages"][4]["metrics"]["compensation"]
    total_2 = second["stages"][4]["metrics"]["compensation"]
    assert total_1 == total_2 == "26.00"
    # 再跑一次纯计算，版本链长度恒定
    again = calculate(raw)
    assert [len(r["commitment_ledger"]) for r in again["stages"][3]["rows"]] == \
           [len(r["commitment_ledger"]) for r in first["stages"][3]["rows"]]


# 裁决六：页面/接口可追到每次变更（版本链 + 扫描落钉 + 失败留痕）
def test_every_change_is_traceable():
    result = calculate(load_sample("amendments.csv"))
    m8 = result["stages"][7]
    a003 = next(r for r in m8["rows"] if r["parcel"] == "A003")
    versions = a003["commitment_ledger"]
    assert [v["version"] for v in versions] == ["v0", "v1"]
    assert all(v["source_lines"] and v["basis"] for v in versions)
    # 每条扫描都能追到当时版本
    assert all(s["commitment_version"] and s["effective_promised_hours"] for s in a003["scans"])
    # 失败改约在累计隔离中可查，且标注保留的上一版本
    codes = {q["scan_id"]: (q["reason"], q.get("rejected_version")) for q in m8["cumulative_quarantine"]}
    assert codes["1022"] == ("AMEND_FAILED", "v0")
    assert codes["1034"] == ("AMEND_CONFLICT", "v1")


def test_amendment_sample_end_to_end_balanced_and_archivable():
    result = calculate(load_sample("amendments.csv"))
    assert len(result["stages"]) == 8
    assert result["stages"][5]["metrics"]["balanced"] is True
    assert result["stages"][6]["metrics"]["ready"] is True
    assert result["stages"][7]["metrics"]["ledger_breaks"] == 0


def test_amendment_sample_via_api(client):
    r = client.post("/api/runs", json={"sample": "amendments.csv"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["stages"][7]["metrics"]["parcels"] == 4
    assert client.get("/api/commitments").status_code == 200
    assert client.get("/commitments").status_code == 200


def test_legacy_samples_still_single_version_ledgers():
    for name in ("dirty.csv", "clean.csv", "legacy.csv"):
        result = calculate(load_sample(name), stop=7)
        for row in result["stages"][3]["rows"]:
            assert len(row["commitment_ledger"]) == 1
            assert row["commitment_ledger"][0]["version"] == "v0"
        assert result["stages"][7]["metrics"]["amended_parcels"] == 0
