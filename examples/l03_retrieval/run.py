"""Run L03 behavior checks and export actual, synthetic observations."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
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

from test_retrieval import RetrievalTests  # noqa: E402

SCOPE = (
    "L03 合成租户数据上的确定性检索、版本和工具授权验证；"
    "覆盖 M4-C2 的本地模拟子集，不是实际身份认证、真实 LLM 抗注入或 MCP OAuth 验收；"
    "不覆盖 M4-C1 恢复与 M4-C3 完整应用回归，不宣布 M4 全部通过，不评定学习者能力。"
)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def source_hashes():
    return {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in ("retrieval.py", "test_retrieval.py", "run.py")}


def diagnostic_without_personal_paths(text, test):
    temporary = getattr(test, "temporary", None)
    for source, replacement in (
        (getattr(temporary, "name", ""), "<case-temp>"),
        (str(HERE), "<example>"),
        (str(HERE.parents[1]), "<repo>"),
        (str(Path.home()), "<home>"),
    ):
        if source:
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
        self.active["diagnostics"].append(
            diagnostic_without_personal_paths(self._exc_info_to_string(err, test), test))

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
        self.active["diagnostics"].append(diagnostic_without_personal_paths(reason, test))
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
    summary = report["summary"]
    lines = ["# L03 本地权限与版本验证报告", "", report["scope"], "",
             f"执行时间：{report['started_at']}。记录来自本次实际运行，全部使用合成数据。",
             f"环境：Python {report['environment']['python']}；SQLite {report['environment']['sqlite']}；{report['environment']['system']}。",
             f"结果：{report['tests_run']} 项，{summary.get('passed', 0)} 通过；其余状态："
             + json.dumps({k: v for k, v in summary.items() if k != "passed"}, ensure_ascii=False) + "。",
             f"执行期间源码保持一致：{report['source_unchanged']}。", "",
             "`test_00` 通过表示复现了错误截断导致的漏召回，并观察到修复结果；不表示错误实现符合业务要求。",
             "所有逐例输入、上下文、引用、授权原因及本地副作用观测见 [report.json](report.json)。",
             "B 合法访问用例含 B 的合成标记；A 请求的上下文、回答及审计单独检查不含该标记。", "",
             "## 实现版本", "", "| 文件 | SHA-256 |", "| --- | --- |"]
    for name, digest in report["source_sha256"].items():
        lines.append(f"| {name} | {digest} |")
    lines += ["", "## 用例结果", "", "| 用例 | 状态 | 秒 |", "| --- | --- | --- |"]
    for case in report["cases"]:
        lines.append(f"| {case['id'].rsplit('.', 1)[-1]} | {case['status']} | {case['duration_seconds']} |")
    for case in report["cases"]:
        lines += ["", "## " + case["id"].rsplit(".", 1)[-1], "", case["description"], "",
                  "预期：", "```json", json.dumps(case["evidence"].get("expected", {}), ensure_ascii=False, indent=2), "```"]
        final = case["evidence"].get("observations", {}).get("final", {})
        if final:
            lines.append("实际正文读取：" + json.dumps(final.get("body_reads", []), ensure_ascii=False) + "。")
            lines.append(f"实际导出台账：{len(final.get('export_effects', []))} 条。完整原因与结果见原始记录。")
        for diagnostic in case["diagnostics"]:
            lines += ["", "~~~text", diagnostic.rstrip(), "~~~"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="运行 L03 本地模拟测试并可选保存真实证据")
    parser.add_argument("--output-dir", type=Path, help="新建报告目录；拒绝覆盖已有目录")
    args = parser.parse_args(argv)
    if args.output_dir is not None:
        try:
            args.output_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            parser.error(f"无法新建报告目录：{exc}")
    hashes = source_hashes()
    started_at = timestamp()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RetrievalTests)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1,
                                     resultclass=EvidenceResult, buffer=True).run(suite)
    summary = {status: sum(c["status"] == status for c in result.cases)
               for status in ("passed", "failed", "error", "skipped", "expected_failure", "unexpected_success")}
    unchanged = source_hashes() == hashes
    successful = result.testsRun > 0 and len(result.cases) == result.testsRun and unchanged and all(
        c["status"] == "passed" for c in result.cases)
    report = {"schema_version": 1, "scope": SCOPE, "started_at": started_at,
              "finished_at": timestamp(), "source_sha256": hashes, "source_unchanged": unchanged,
              "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                              "system": platform.system()},
              "tests_run": result.testsRun, "successful": successful,
              "summary": summary, "cases": result.cases}
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
        print("运行期间源码发生变化，本次报告不得作为该版本的完整验收。", file=sys.stderr)
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
