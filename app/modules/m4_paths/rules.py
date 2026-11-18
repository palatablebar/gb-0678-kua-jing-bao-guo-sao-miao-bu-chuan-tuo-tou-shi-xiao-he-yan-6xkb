from collections import defaultdict
from app.values import instant
from app.reasons import reject,sources
from app.commitments.ledger import AMEND_NODE,build_ledger,stamp_scan
PRIORITY={"ACCEPT":0,"DEPART":1,"CUSTOMS":2,"DELIVERED":3}
def evaluate(rows,context):
    groups=defaultdict(list);good=[];bad=[]
    for r in rows:groups[r["parcel"]].append(r)
    for parcel,events in sorted(groups.items()):
        amendments=sorted((e for e in events if e["node"]==AMEND_NODE),key=lambda r:(instant(r["event_utc"]),r["scan_id"]))
        physical=sorted((e for e in events if e["node"]!=AMEND_NODE),key=lambda r:(instant(r["event_utc"]),PRIORITY[r["node"]],r["scan_id"]))
        seen={};valid=[];last=-1
        for e in physical:
            time=e["event_utc"]
            if time in seen and seen[time]!=e["node"]:bad.append(reject(e,"SIMULTANEOUS_CONFLICT","同刻扫描节点冲突"));continue
            seen[time]=e["node"]
            if PRIORITY[e["node"]]<last:bad.append(reject(e,"PATH_REGRESSION","扫描路径倒退"));continue
            last=PRIORITY[e["node"]];valid.append(e)
        accepts=[e for e in valid if e["node"]=="ACCEPT"]
        if not accepts:
            bad.extend(reject(e,"MISSING_ACCEPT","缺少收件扫描") for e in valid)
            # 没有收件锚点时，改约确认无承诺可改，逐条隔离保留原始依据
            bad.extend(reject(a,"AMEND_BEFORE_ACCEPT","缺少收件扫描，改约无生效锚点") for a in amendments)
            continue
        delivery=next((e for e in valid if e["node"]=="DELIVERED"),None)
        first=accepts[0]
        ledger,rejected_amend=build_ledger(first["event_utc"],delivery["event_utc"] if delivery else None,
                                           first["promised_hours"],sources(first),amendments)
        bad.extend(rejected_amend)
        source_lines=[line for e in valid for line in sources(e)]
        # 成功改约的来源行计入该票血缘（失败改约已隔离，不并入），保证逐行对平
        source_lines.extend(line for v in ledger[1:] for line in v["source_lines"])
        stamps=[stamp_scan(ledger,e) for e in valid]
        good.append({**first,"_sources":source_lines,"accepted_at":first["event_utc"],"delivered_at":delivery["event_utc"] if delivery else None,"delivery_uploaded_at":delivery["received_utc"] if delivery else None,"scan_count":len(valid),"path":" → ".join(e["node"] for e in valid),"reported":delivery["reported"] if delivery else first["reported"],
                     "commitment_ledger":ledger,
                     "amendment_count":len(amendments),
                     "amendment_rejected":len(rejected_amend),
                     "scans":stamps})
    return {"rows":good,"quarantine":bad,"metrics":{"parcels":len(good),"delivered":sum(r["delivered_at"] is not None for r in good),"path_errors":len(bad),"amendments":sum(r["amendment_count"] for r in good),"amendments_rejected":sum(r["amendment_rejected"] for r in good)}}
