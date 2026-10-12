# L04 可运行练习：失败、重试与评测分母

学习路径：[Q041](../../questions/10-evaluation.md#q041) / [Q042](../../questions/10-evaluation.md#q042) → [G03](../../learning/guides/evaluation-regression.md) → [L04](../../learning/labs/evaluation-missing-failures.md) → [M3-C2](../../roadmap/milestones.md#m3-c2)。

这是 **8 个合成任务的离线计算练习**。实际执行的是 JSON 校验、逐次成本累加、确定性成功判断和门槛比较；没有模型调用、网络请求或真实业务日志。模型评审的 `pass` 是公开夹具里的故障注入标记，不能覆盖禁止副作用。

## 运行

Python 3.10+，仅用标准库。在仓库根目录运行：

```sh
python3 examples/l04_evaluation/run.py
python3 -m unittest discover -s examples/l04_evaluation -p "test_*.py" -v
python3 examples/l04_evaluation/evaluation.py
```

前两条执行同一组行为测试；第三条输出完整夹具的逐任务计算 JSON。计算器退出码 0 表示输入有效且计算完成，**不表示候选通过门槛**；必须看 `candidate_passes` 与 `failed_gates`。不合法输入返回 2，且不产生指标报告。

读取自己保存的、符合固定合同的 JSON 时：

```sh
python3 examples/l04_evaluation/evaluation.py path/to/input.json
```

这是固定练习，任务清单、版本、attempt 配额与单位均受校验；它不是可接任意生产日志的通用平台。原始格式见 `evaluation.py` 的 `fixture()`，以及下方报告中的 `fixture`。改变任务规模或实验合同需改代码和测试，不能靠删 manifest 中失败任务改变本次分母。

保存自己的实际验收记录，用一个尚不存在的目录：

```sh
python3 examples/l04_evaluation/run.py --output-dir .lab-output/l04-first-run
```

报告保存本次运行的环境、三份 Python 源码 SHA-256、合成输入及其规范 JSON 哈希、逐用例原始输入/观测/拒绝原因、原始 unittest 输出。已有目录拒绝覆盖；失败、错误、跳过或运行期间源码变化不会成为全通过。记录不含主机名或个人绝对路径。`.lab-output/` 不进入 Git。

仓库的[实际运行报告](verification/report.md)和[原始 JSON](verification/report.json)只对应其中记录的源码哈希与合成条件。修改代码后应重新运行，不沿用旧报告证明新代码。

## 固定实验与错误对照

| 项目 | baseline-v1 | candidate-v1 |
| --- | --- | --- |
| manifest | case-1 至 case-8 | 相同 8 个任务 |
| 最终记录 | 每例恰好一条；case-8 超时 | 每例恰好一条；case-8 超时 |
| attempt 配额 | 每例一次 | case-1..4 一次，case-5..8 两次 |
| 目标达成 | 1,1,0,1,1,1,1,0 | 1,1,1,1,1,1,1,0 |
| 禁止副作用 | 全部为 0 | case-7 为 1，其余为 0 |
| 每次成本 | 每例 2 | 前四例 2，后四例每次分别 1、2 |
| 端到端毫秒 | 100,120,130,150,160,170,200,300 | 100,110,120,130,150,160,180,400 |

成本是本地模拟单位，不是 token 或模型价格。额外的逐次耗时也是合成的：有重试时第一次 40 毫秒，其余时间计入末次；最终端到端耗时必须至少覆盖所有 attempt 时间。真实应用还要测量排队、退避和网络等待。

`test_00` 从同一份验证后的数据实际运行错误对照：只留 completed、接受目标或模型通过、只累计最后一个 attempt。它会写出候选 **7/7、成本 16、p95 180 毫秒**。该对照明确标为错误且不参与正式门槛判断；测试 PASS 表示复现了错误并验证修正结果。

修正结果：

- 两版分母都是 8，实际成功均为 **6/8 = 75%**。case-7 的模型 `pass` 不覆盖禁止副作用；case-8 超时保留在分母与耗时中。
- 成本累计所有 attempt：**16 对 20，增加 25%**，包括失败和超时尝试。
- nearest-rank p95 取 `ceil(0.95 × 8) = 8`，得到 **300 对 400 毫秒**，不用插值，也不删除超时。
- 练习要求成功率不下降、禁止副作用为零、成本与 p95 不超过 baseline 的 110%。候选仅成功率门槛满足，另外三项失败，最终 **不通过**。

110% 只是本练习约定。边界测试还构造了真正满足全部条件的修改版，并检查恰好 110% 可通过、略超成本边界会失败，避免脚本把所有候选一律拒绝。

## 输入校验与证据边界

每条 final 与 attempt 都有任务 ID、实现版本和状态；attempt 另有稳定 ID 与连续序号。脚本拒绝缺失、重复、未知任务、混版、序号/配额错误、丢失重试成本的明细，以及 final 与末次目标/状态或累计副作用矛盾的输入。

数值必须是有限、非负的 JSON 数字，且不超过 10¹²；不接受布尔值、字符串、NaN/Infinity。计数必须是整数。JSON 重复键、异常字段、过大或损坏文件也拒绝。成本比较用输入十进制表示进行 `Decimal` 累加；输出显示值转换为 JSON 数字，原始输入始终保留。

`claimed_success` 若提供，必须符合 `completed AND goal_achieved AND forbidden_effects == 0`；不符合则拒绝。`model_judgment` 仅作非权威备注，允许与确定性结果冲突，以展示模型高分为什么不能替代业务事实。`timed_out/error` 不能伪称已确认目标达成；前一次尝试留下的禁止副作用不能被最终成功抹掉。

这些检查证明**所给结构化证据之间的一致性及计算口径**，不能鉴定日志真实性，也不能发现被上游成套伪造但内部一致的目标、成本或事件。真实系统需要独立记录完整任务分配、实际调用及业务副作用。这里的固定配额不是生产系统的重试策略。

## 与路线和个人自检的关系

本例覆盖 [M3-C2](../../roadmap/milestones.md#m3-c2) 中完整任务、失败分类、成本与延迟的计算子集；不实现检索或生成质量评估，也没有两版真实应用的因果对照。与 [AT11/AT12](../../assessment/manual.md#d6) 使用相同原则，但本例是 8 任务，测评题的 4/5 任务夹具不同，不能直接复制数字作为答卷。

8 个合成样本的 nearest-rank p95 恰好等于最大值，不能代表线上尾延迟分布，不能证明统计显著改进。仓库测试通过不等于学习者独立掌握，也不能自动提高自检档位或宣布 M3/M4 全部通过。看过实现或核心解法后，如实记录参考范围；再修改一个约束、独立预测、运行并解释差异。

建议保留 [项目证据](../../templates/project-evidence.md)和[复习记录](../../templates/review-log.csv)：记录原始输入、版本、预期、实际、错误原因以及仍未验证的边界。

## 文件

- [evaluation.py](evaluation.py)：固定合同、严格输入校验、正确计算与错误对照、JSON 计算入口。
- [test_evaluation.py](test_evaluation.py)：行为测试及逐例证据。
- [run.py](run.py)：执行测试、记录源码/输入哈希和实际输出。

[返回研习](../../learning/README.md) · [M3-C2](../../roadmap/milestones.md#m3-c2)
