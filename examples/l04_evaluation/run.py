"""Run the real L04 unittest suite and save versioned synthetic evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import sys
import time
import unittest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from evaluation import evaluate, fixture  # noqa: E402
from test_evaluation import EvaluationTests  # noqa: E402

SCOPE = (
    "L04 固定八任务合成数据的离线配对评测、逐次成本、nearest-rank p95 与输入拒绝验证；"
    "支持 M3-C2 的计算口径子集，不运行真实模型或业务应用。八样本不能估计线上尾延迟，"
    "本例的 110% 门槛不是行业标准；不宣布完整 M3/M4 通过，不鉴定日志真实性或学习者能力。"
)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def source_hashes():
    return {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in ("evaluation.py", "test_evaluation.py", "run.py")}


def sanitize(text):
    for source, replacement in ((str(HERE), "<example>"),
                                (str(HERE.parents[1]), "<repo>"),
                                (str(Path.home()), "<home>")):
        text = text.replace(source, replacement)
    return re.sub(r'File "([^"<>][^"]*)"',
                  lambda m: f'File "<source>/{Path(m.group(1)).name}"', text)


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []

    def startTest(self, test):
        self.active = {"id": test.id(), "description": test.shortDescription() or test.id(),
                       "status": "running", "diagnostics": []}
        self.started = time.monotonic()
        super().startTest(test)

    def record_error(self, test, err, status):
        if self.active["status"] != "error":
            self.active["status"] = status
        self.active["diagnostics"].append(sanitize(self._exc_info_to_string(err, test)))

    def addSuccess(self, test):
        self.active["status"] = "passed"
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.record_error(test, err, "failed")
        super().addFailure(test, err)

    def addError(self, test, err):
        self.record_error(test, err, "error")
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.active["status"] = "skipped"
        self.active["diagnostics"].append(sanitize(reason))
        super().addSkip(test, reason)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.record_error(test, err, "failed" if issubclass(err[0], test.failureException) else "error")
        super().addSubTest(test, subtest, err)

    def addExpectedFailure(self, test, err):
        self.record_error(test, err, "expected_failure")
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self.active["status"] = "unexpected_success"
        super().addUnexpectedSuccess(test)

    def stopTest(self, test):
        self.active["duration_seconds"] = round(time.monotonic() - self.started, 6)
        self.active["evidence"] = getattr(test, "evidence", {})
        self.cases.append(self.active)
        super().stopTest(test)


def markdown(report):
    comparison = report["comparison"]
    summary = report["summary"]
    lines = ["# L04 离线评测实际运行报告", "", report["scope"], "",
             f"执行时间：{report['started_at']}。环境：Python {report['environment']['python']} / {report['environment']['system']}。",
             f"本次运行 {report['tests_run']} 项，{summary['passed']} 通过；失败 {summary['failed']}、错误 {summary['error']}、跳过 {summary['skipped']}。",
             f"源码执行前后保持一致：{report['source_unchanged']}。本报告全部为合成证据，没有真实用户或模型结果。", "",
             "## 固定实验的实际计算", "", "| 版本 | 实际成功 / 全任务 | 成本（本地单位） | p95（毫秒） | 禁止副作用 |",
             "| --- | --- | --- | --- | --- |"]
    for role in ("baseline", "candidate"):
        run = comparison[role]
        lines.append(f"| {run['version']} | {run['successes']}/{run['denominator']} = {run['success_rate_percent']}% | {run['total_cost']} | {run['p95']['value_ms']} | {run['forbidden_effects']} |")
    lines += ["", f"成本增加：{comparison['cost_increase_percent']}%。nearest-rank p95：ceil(0.95 × 8) = 8。",
              "候选通过全部门槛：" + str(comparison["candidate_passes"]) + "；未通过：" + ", ".join(comparison["failed_gates"]) + "。", "",
              "错误对照实际得到候选 7/7、只计末次 attempt 的成本 16；丢掉超时后 p95 错变成 180 毫秒。",
              "test_00 的通过表示已观察到这个错误对照并验证修正结果，不表示候选或错误算法通过门槛。", "",
              "## 逐任务结果", "", "| 版本 / 任务 | 终态 | 目标 | 禁止副作用 | 实际成功 | 累计成本 | 耗时 | 失败原因 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for role in ("baseline", "candidate"):
        for case in comparison[role]["cases"]:
            lines.append(f"| {role} / {case['case_id']} | {case['status']} | {case['goal_achieved']} | {case['forbidden_effects']} | {case['success']} | {case['total_cost']} | {case['latency_ms']} | {', '.join(case['failure_reasons']) or '—'} |")
    lines += ["", "## 版本与原始证据", "", "| 文件 | SHA-256 |", "| --- | --- |"]
    for name, digest in report["source_sha256"].items():
        lines.append(f"| {name} | {digest} |")
    lines += ["", f"合成输入规范 JSON SHA-256：`{report['fixture_sha256']}`。",
              "完整输入、每个 attempt、模型评审备注、逐例拒绝原因、门槛和原始 unittest 输出均见 [report.json](report.json)。", "",
              "## 行为测试", "", "| 用例 | 结果 | 秒 |", "| --- | --- | --- |"]
    for case in report["cases"]:
        lines.append(f"| {case['id'].rsplit('.', 1)[-1]} | {case['status']} | {case['duration_seconds']} |")
    lines += ["", "## 本次原始测试输出", "", "```text", report["raw_test_output"].rstrip(), "```", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="实际执行 L04 标准库测试，并可选保存合成验收证据")
    parser.add_argument("--output-dir", type=Path, help="新报告目录；拒绝覆盖已有目录")
    args = parser.parse_args(argv)
    if args.output_dir is not None:
        try:
            args.output_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            parser.error(f"无法新建报告目录：{exc}")
    hashes = source_hashes()
    started_at = timestamp()
    raw_stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EvaluationTests)
    result = unittest.TextTestRunner(stream=raw_stream, verbosity=2, resultclass=EvidenceResult, buffer=True).run(suite)
    raw_output = sanitize(raw_stream.getvalue())
    sys.stderr.write(raw_output)
    summary = {status: sum(case["status"] == status for case in result.cases)
               for status in ("passed", "failed", "error", "skipped", "expected_failure", "unexpected_success")}
    unchanged = source_hashes() == hashes
    successful = result.testsRun > 0 and len(result.cases) == result.testsRun and unchanged and all(
        case["status"] == "passed" for case in result.cases)
    raw_input = fixture()
    report = {"schema_version": 1, "scope": SCOPE, "started_at": started_at, "finished_at": timestamp(),
              "source_sha256": hashes, "source_unchanged": unchanged,
              "environment": {"python": platform.python_version(), "system": platform.system()},
              "fixture_sha256": hashlib.sha256(json.dumps(raw_input, sort_keys=True, ensure_ascii=False,
                                                          separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest(),
              "fixture": raw_input, "comparison": evaluate(raw_input),
              "tests_run": result.testsRun, "successful": successful, "summary": summary,
              "cases": result.cases, "raw_test_output": raw_output}
    if args.output_dir is not None:
        try:
            (args.output_dir / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            (args.output_dir / "report.md").write_text(markdown(report), encoding="utf-8")
        except (OSError, ValueError) as exc:
            print(f"报告写入失败：{exc}", file=sys.stderr)
            return 1
    print(SCOPE)
    print(f"本次执行 {result.testsRun} 项；通过 {summary['passed']}，失败 {summary['failed']}，错误 {summary['error']}，跳过 {summary['skipped']}。")
    print("固定夹具的 candidate_passes=False 是预期业务结论，与测试是否通过分开。")
    if not unchanged:
        print("运行期间源码改变，报告不能作为该版本完整验收。", file=sys.stderr)
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
