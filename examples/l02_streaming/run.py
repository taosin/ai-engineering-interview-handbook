"""Run L02 checks and export observed traces, never a fabricated M4 result."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import sqlite3
import sys
import time
import unittest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from test_streaming import StreamingTests  # noqa: E402

SCOPE = (
    "L02 本地服务桩的事件重放、页面重建、游标快照、任务隔离与取消竞态验证；"
    "使用合成事件和 SQLite 本地副作用，不涉及真实网络、浏览器 EventSource、真实 LLM 或外部工具；"
    "未覆盖完整应用既有回归，不宣布 M4 全部通过，不评定学习者能力。"
)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def source_hashes():
    return {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in ("streaming.py", "test_streaming.py", "run.py")}


def redact_paths(text, test=None):
    temporary = getattr(test, "temporary", None)
    for source, replacement in ((getattr(temporary, "name", ""), "<case-temp>"),
                                (str(HERE), "<example>"),
                                (str(HERE.parents[1]), "<repo>"),
                                (str(Path.home()), "<home>")):
        if source:
            text = text.replace(source, replacement)
    return re.sub(r'File "([^"<>][^"]*)"',
                  lambda match: f'File "<source>/{Path(match.group(1)).name}"', text)


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
        self.active["diagnostics"].append(redact_paths(self._exc_info_to_string(err, test), test))

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
        self.active["diagnostics"].append(redact_paths(reason, test))
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
        self.active["raw_output"] = {
            "stdout": redact_paths(self._stdout_buffer.getvalue(), test) if self._stdout_buffer else "",
            "stderr": redact_paths(self._stderr_buffer.getvalue(), test) if self._stderr_buffer else "",
        }
        self.cases.append(self.active)
        super().stopTest(test)


class Tee:
    def __init__(self):
        self.captured = io.StringIO()
        self.output = sys.stderr

    def write(self, text):
        self.captured.write(text)
        self.output.write(text)

    def flush(self):
        self.output.flush()


def markdown(report):
    lines = ["# L02 流式恢复与取消本地验证报告", "", report["scope"], "",
             "执行时间：" + report["started_at"] + "。以下记录来自本次实际测试执行。",
             f"环境：Python {report['environment']['python']}；SQLite {report['environment']['sqlite']}；{report['environment']['system']}。",
             f"结果：{report['tests_run']} 项，{report['summary'].get('passed', 0)} 通过。",
             f"执行期间源码保持一致：{report['source_unchanged']}。", "",
             "`test_00` 通过表示实际复现了错误重放导致的重复文字，并验证修复；不代表错误实现符合要求。",
             "取消只阻止本地事务屏障之后尚未启动的工具；已发生的本地副作用保留，不承诺外部工具回滚。",
             "每例完整事件、应用/去重/缺口/快照轨迹和原始输出见 [report.json](report.json)。", "",
             "## 实现版本", "", "| 文件 | SHA-256 |", "| --- | --- |"]
    for name, digest in report["source_sha256"].items():
        lines.append(f"| {name} | {digest} |")
    lines += ["", "## 用例结果", "", "| 用例 | 状态 | 秒 |", "| --- | --- | --- |"]
    for case in report["cases"]:
        lines.append(f"| {case['id'].rsplit('.', 1)[-1]} | {case['status']} | {case['duration_seconds']} |")
    for case in report["cases"]:
        lines += ["", "## " + case["id"].rsplit(".", 1)[-1], "", case["description"], "",
                  "预期：", "```json", json.dumps(case["evidence"].get("expected", {}), ensure_ascii=False, indent=2), "```"]
        observed = case["evidence"].get("observations", {}).get("final", {})
        if observed:
            lines += ["实际客户端任务状态：", "```json",
                      json.dumps(observed.get("client", {}).get("runs", []), ensure_ascii=False, indent=2), "```",
                      "实际本地工具副作用：" + str(len(observed.get("service", {}).get("tool_effects", []))) + " 条。"]
        for diagnostic in case["diagnostics"]:
            lines += ["", "~~~text", diagnostic.rstrip(), "~~~"]
    lines += ["", "## 本次 unittest 原始输出（个人路径脱敏）", "", "~~~text", report["test_output"].rstrip(), "~~~"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="运行 L02 本地事件/取消验证并可选保存实际报告")
    parser.add_argument("--output-dir", type=Path, help="新建报告目录；拒绝覆盖已有目录")
    args = parser.parse_args(argv)
    if args.output_dir is not None:
        try:
            args.output_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            parser.error(f"无法新建报告目录：{exc}")
    hashes = source_hashes()
    started_at = timestamp()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(StreamingTests)
    stream = Tee()
    result = unittest.TextTestRunner(stream=stream, verbosity=2,
                                     resultclass=EvidenceResult, buffer=True).run(suite)
    summary = {status: sum(case["status"] == status for case in result.cases)
               for status in ("passed", "failed", "error", "skipped", "expected_failure", "unexpected_success")}
    unchanged = source_hashes() == hashes
    successful = result.testsRun > 0 and len(result.cases) == result.testsRun and unchanged and all(
        case["status"] == "passed" for case in result.cases)
    report = {"schema_version": 1, "scope": SCOPE, "started_at": started_at,
              "finished_at": timestamp(), "source_sha256": hashes, "source_unchanged": unchanged,
              "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                              "system": platform.system()},
              "tests_run": result.testsRun, "successful": successful, "summary": summary,
              "test_output": redact_paths(stream.captured.getvalue()), "cases": result.cases}
    if args.output_dir is not None:
        try:
            (args.output_dir / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (args.output_dir / "report.md").write_text(markdown(report), encoding="utf-8")
        except OSError as exc:
            print(f"报告写入失败：{exc}", file=sys.stderr)
            return 1
    print(SCOPE)
    print(f"本次执行 {result.testsRun} 项；通过 {summary['passed']}，失败 {summary['failed']}，"
          f"错误 {summary['error']}，跳过 {summary['skipped']}。")
    if not unchanged:
        print("运行期间源码发生变化，本次报告不能作为该版本验收。", file=sys.stderr)
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
