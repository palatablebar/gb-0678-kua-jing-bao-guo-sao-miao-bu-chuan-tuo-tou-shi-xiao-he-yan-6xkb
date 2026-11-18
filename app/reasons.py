REASONS={"BAD_COLUMNS":"列数不匹配","EMPTY_VALUE":"必填值为空","INVALID_NUMBER":"数字格式错误","INVALID_TIME":"时间缺少偏移或格式错误","DUPLICATE_CONFLICT":"同键取值冲突","UNKNOWN_REFERENCE":"引用不存在","STALE_VERSION":"版本已更新","EMPTY_FILE":"文件为空","HEADER_ONLY":"仅有表头","BLANK_ONLY":"全部为空行","AMEND_FAILED":"改约失败","AMEND_BEFORE_ACCEPT":"改约早于收件","AMEND_AFTER_DELIVERY":"改约晚于妥投","AMEND_CONFLICT":"同刻改约冲突","AMEND_WITHOUT_PARCEL":"改约缺少包裹","LEDGER_GAP":"承诺账本断层","LEDGER_MISSING":"包裹缺少承诺账本"}
def reject(row, code, detail):
    return {**row,"reason":code,"detail":detail}
def sources(row):
    return row.get("_sources", [row.get("_line",0)])
