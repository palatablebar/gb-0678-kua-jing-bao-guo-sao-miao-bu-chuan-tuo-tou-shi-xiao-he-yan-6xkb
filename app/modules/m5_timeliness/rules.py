from datetime import datetime,timedelta,time
from zoneinfo import ZoneInfo
from decimal import Decimal
from app.values import instant,number,money
from app.errors import DomainError
from app.commitments.ledger import version_at
HOLIDAYS={"JP":{"2026-11-03","2026-11-23"},"US":{"2026-11-26"},"DE":{"2026-10-03"}}
def working_hours(start,end,zone,holidays):
    if end<start:raise DomainError("NEGATIVE_INTERVAL","妥投早于收件")
    tz=ZoneInfo(zone);cursor=start;seconds=Decimal(0)
    while cursor<end:
        local=cursor.astimezone(tz);next_day=datetime.combine(local.date()+timedelta(days=1),time.min,tzinfo=tz).astimezone(cursor.tzinfo)
        stop=min(end,next_day)
        if local.weekday()<5 and local.date().isoformat() not in holidays:seconds+=Decimal(str((stop-cursor).total_seconds()))
        cursor=stop
    return seconds/3600
def segment_ledger(row,end):
    """以改约确认时点切出承诺分段；生效前的扫描落在旧承诺段，生效后落在新承诺段。

    每段半开区间 [effective_from, effective_to)，末段延伸到妥投/核算时点。
    """
    ledger=row.get("commitment_ledger")
    if not ledger:
        return [{"version":"v0","promised_hours":row["promised_hours"],"start":instant(row["accepted_at"]),"stop":end}]
    segments=[]
    for index,version in enumerate(ledger):
        start=max(instant(version["effective_from"]),instant(row["accepted_at"]))
        boundary=instant(version["effective_to"]) if version["effective_to"] else end
        stop=min(end,boundary)
        if start>=stop:continue
        segments.append({"version":version["version"],"promised_hours":version["promised_hours"],"start":start,"stop":stop})
    return segments
def evaluate(rows,context):
    p=context.get("parameters",{});as_of=instant(p.get("as_of","2026-11-18T00:00:00Z"));rate=number(p.get("hourly_compensation","1.00"))
    if rate<0:raise DomainError("BAD_RATE","赔付费率不能为负")
    good=[]
    for row in rows:
        start=instant(row["accepted_at"]);end=instant(row["delivered_at"]) if row.get("delivered_at") else max(start,as_of)
        holidays=set(p.get("holidays",{}).get(row["destination"],HOLIDAYS.get(row["destination"],set())))
        # 逐承诺版本分段：各段用当时有效承诺独立计时，结论不追溯
        detail=[];total_hours=Decimal(0);total_late=Decimal(0)
        for seg in segment_ledger(row,end):
            hours=working_hours(seg["start"],seg["stop"],row["zone"],holidays)
            late=max(Decimal(0),hours-number(seg["promised_hours"]))
            total_hours+=hours;total_late+=late
            detail.append({"version":seg["version"],"promised_hours":seg["promised_hours"],"from":seg["start"].isoformat(),"to":seg["stop"].isoformat(),"working_hours":str(hours),"late_hours":str(late)})
        # 兼容无账本的直接调用（单段，承诺取行内值）
        if not detail:
            hours=working_hours(start,end,row["zone"],holidays)
            late=max(Decimal(0),hours-number(row["promised_hours"]))
            total_hours=hours;total_late=late
            detail=[{"version":"v0","promised_hours":str(row["promised_hours"]),"from":start.isoformat(),"to":end.isoformat(),"working_hours":str(hours),"late_hours":str(late)}]
        comp=min(number(row["declared_value"])*Decimal("0.10"),total_late*rate)
        # 每票唯一承诺与赔付结论：当前有效版本 + 唯一 expected
        current=version_at(row["commitment_ledger"],end) if row.get("commitment_ledger") else {"version":"v0","promised_hours":str(row["promised_hours"])}
        good.append({**row,"working_hours":str(total_hours),"late_hours":str(total_late),"expected":money(comp),"sla":"超时" if total_late>0 else "达标","clock_end":end.isoformat(),
                     "promised_hours":current["promised_hours"],"active_commitment_version":current["version"],"commitment_segments":detail})
    return {"rows":good,"quarantine":[],"metrics":{"parcels":len(good),"late_parcels":sum(r["sla"]=="超时" for r in good),"compensation":money(sum((number(r["expected"]) for r in good),Decimal(0)))}}
