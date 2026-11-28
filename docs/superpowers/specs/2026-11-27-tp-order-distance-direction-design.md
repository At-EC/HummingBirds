# 同向预期 TP 距离过滤设计

## 目标

防止新挂单成交后生成的 TP 与已有同向开放 TP 在价格附近淤积。入口价格过滤已按要求删除。

## 已确认规则

1. 入口价格不再与开放 TP 比较，不执行入口价格过滤。
2. 对 LIMIT / LIMIT_MAKER TP，按新挂单方向计算预期 TP：
   - BUY：`price × (1 + take_profit)`，方向为 SELL。
   - SELL：`price × (1 - take_profit)`，方向为 BUY。
3. 预期 TP 只与已有同向开放 TP 比较。BUY 持仓对应 SELL TP，SELL 持仓对应 BUY TP。
4. 比较使用 `abs(candidate - existing) / existing < tolerance`。等于容差时允许挂单，`0` 禁用过滤。
5. MARKET TP 不执行预期 TP 过滤。亏损退出形成的开放 TP 同样计入已有 TP。
6. 只跳过冲突的新档位，不撤销已有订单，其他档位继续评估。

## 实现范围

仅修改 `controllers/generic/pmm_mister_loss_exit.py` 和对应 Controller 回归测试。先运行测试并更新 Paper，不直接修改实盘。
