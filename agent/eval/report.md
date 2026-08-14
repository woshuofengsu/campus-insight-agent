# Agent 竞争力评测报告

- 场景总数：19（standard / unseen / generic）
- 关键词兜底命中率：57.9%
- 完整路由命中率：100.0%

| 分组 | 关键词命中 | 完整命中 |
|---|---|---|
| standard | 100.0% | 100.0% |
| unseen | 100.0% | 100.0% |
| generic | 0.0% | 100.0% |

- 幻觉编号检出率：100.0%（2/2）
- 真实编号误判：否 [OK]

| 分类 | 输入 | 期望 | 关键词 | 完整 |
|---|---|---|---|---|
| standard | 3号楼电梯困人了 | report_issue | OK | OK |
| standard | 社区脉搏 | get_community_pulse | OK | OK |
| standard | 今天天气怎么样 | get_weather | OK | OK |
| standard | 看看有哪些提案 | get_proposals | OK | OK |
| standard | 我的工单进展如何 | query_my_issues | OK | OK |
| standard | 统计一下解决率 | get_governance_stats | OK | OK |
| unseen | 我家楼道灯忽闪忽闪的 | report_issue | OK | OK |
| unseen | 车轱辘陷坑里了 | report_issue | OK | OK |
| unseen | 电梯一开一合吱吱响 | report_issue | OK | OK |
| unseen | 水龙头拧不紧了 | report_issue | OK | OK |
| unseen | 想看看最近小区有啥新鲜事 | get_community_pulse | OK | OK |
| generic | 我家门口地砖翘起来了 | report_issue | MISS | OK |
| generic | 楼道里老有股难闻的味 | report_issue | MISS | OK |
| generic | 小区喷水池不喷了 | report_issue | MISS | OK |
| generic | 单元门锁舌卡住开不了 | report_issue | MISS | OK |
| generic | 绿化带被人搭了棚子 | report_issue | MISS | OK |
| generic | 消防通道被一辆车堵死了 | report_issue | MISS | OK |
| generic | 活动室乒乓球桌腿断了 | report_issue | MISS | OK |
| generic | 想看看大家最近都在聊什么 | get_topics | MISS | OK |