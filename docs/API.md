# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

## 承诺改约（M8 `/api/commitments`）

节点列出现`改约`/`承诺变更`时归一为`AMEND`，代表客户确认新承诺。新承诺自该行`event_time`（确认时点）生效，与`received_time`（补传上传时点）无关。M4输出每票`commitment_ledger`版本链与`scans`落钉；M5按版本分段计时并给出每票唯一`sla`/`expected`；M8校验账本不变量并返回版本链、扫描落钉与改约隔离（AMEND_FAILED/AMEND_BEFORE_ACCEPT/AMEND_AFTER_DELIVERY/AMEND_CONFLICT）。样例`amendments.csv`覆盖成功改约、失败保留、同刻冲突、收件前与妥投后改约。
