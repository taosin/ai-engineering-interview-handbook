"""Run L01 assertions and optionally export their observed evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from test_recovery import RecoveryTests  # noqa: E402


SCOPE = (
    "L01 本地库存恢复示例；不代表 M4 全部验收通过，不包含租户权限验收；"
    "未覆盖完整应用既有回归；不评定学习者能力。"
)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self.active = {}

    def startTest(self, test):
        self.active = {
            "id": test.id(),
            "description": test.shortDescription() or test.id(),
            "status": "running",
            "diagnostics": [],
        }
        self.started = time.monotonic()
        super().startTest(test)

    def addSuccess(self, test):
        self.active["status"] = "passed"
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.active["status"] = "failed"
        self.active["diagnostics"].append(self._exc_info_to_string(err, test))
        super().addFailure(test, err)

    def addError(self, test, err):
        self.active["status"] = "error"
        self.active["diagnostics"].append(self._exc_info_to_string(err, test))
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.active["status"] = "skipped"
        self.active["diagnostics"].append(reason)
        super().addSkip(test, reason)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.active["status"] = "failed"
            self.active["diagnostics"].append(
                f"{subtest.id()}\n{self._exc_info_to_string(err, test)}"
            )
        super().addSubTest(test, subtest, err)

    def stopTest(self, test):
        self.active["duration_seconds"] = round(time.monotonic() - self.started, 4)
        self.active["evidence"] = getattr(test, "evidence", {})
        self.cases.append(self.active)
        super().stopTest(test)


def markdown(report):
    summary = report["summary"]
    lines = [
        "# L01 恢复验证报告",
        "",
        report["scope"],
        "",
        f"执行时间：{report['started_at']}。以下记录来自本次运行。",
        f"环境：Python {report['environment']['python']}（{report['environment']['implementation']}）；SQLite {report['environment']['sqlite']}。",
        f"结果：{summary['passed']} 通过，{summary['failed']} 失败，"
        f"{summary['error']} 错误，{summary['skipped']} 跳过。",
        "",
        "每个用例使用独立临时目录，初始库存为 10。完整业务/Agent 快照、"
        "预期与过程证据保存在同目录的 `report.json`；临时数据库执行后清理。",
        "",
        "源码 SHA256：",
        "",
        *[f"- `{name}`：`{digest}`" for name, digest in report["source_sha256"].items()],
        "",
        "| 用例 | 状态 | 秒 |",
        "| --- | --- | --- |",
    ]
    for case in report["cases"]:
        lines.append(f"| {case['id'].rsplit('.', 1)[-1]} | {case['status']} | {case['duration_seconds']} |")
    for case in report["cases"]:
        lines.extend([
            "", f"## {case['id'].rsplit('.', 1)[-1]}", "",
            case["description"], "",
            f"状态：**{case['status']}**。", "",
            "预期：", "```json",
            json.dumps(case["evidence"].get("expected", {}), ensure_ascii=False, indent=2),
            "```",
        ])
        final = case["evidence"].get("observations", {}).get("final", {})
        tool = final.get("tool", {})
        if tool:
            lines.append(
                f"观测：库存 {json.dumps(tool.get('stock'), ensure_ascii=False)}；"
                f"有效预留记录 {len(tool.get('reservations', []))} 条。"
            )
        for diagnostic in case["diagnostics"]:
            # Tilde fences keep any backticks from captured exceptions harmless.
            lines.extend(["", "~~~text", diagnostic.rstrip(), "~~~"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="运行 L01 恢复验收并可选导出证据报告")
    parser.add_argument("--output-dir", type=Path, help="新建报告目录；拒绝覆盖已存在目录")
    options = parser.parse_args(argv)
    if options.output_dir is not None:
        try:
            options.output_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            parser.error(f"无法新建输出目录：{exc}")
    started_at = timestamp()
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RecoveryTests)
    result = unittest.TextTestRunner(
        stream=sys.stderr, verbosity=1, resultclass=EvidenceResult, buffer=True
    ).run(suite)
    summary = {
        status: sum(case["status"] == status for case in result.cases)
        for status in ("passed", "failed", "error", "skipped")
    }
    report = {
        "schema_version": 1,
        "scope": SCOPE,
        "started_at": started_at,
        "finished_at": timestamp(),
        "duration_seconds": round(time.monotonic() - started, 4),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "sqlite": sqlite3.sqlite_version,
        },
        "source_sha256": {
            f"examples/l01_recovery/{name}": hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in ("recovery.py", "test_recovery.py", "run.py")
        },
        "tests_run": result.testsRun,
        "successful": result.wasSuccessful(),
        "summary": summary,
        "cases": result.cases,
    }
    if options.output_dir is not None:
        try:
            (options.output_dir / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (options.output_dir / "report.md").write_text(markdown(report), encoding="utf-8")
        except OSError as exc:
            print(f"报告写入失败：{exc}", file=sys.stderr)
            return 1
    print(SCOPE)
    print(
        f"本次执行 {result.testsRun} 项：{summary['passed']} 通过，"
        f"{summary['failed']} 失败，{summary['error']} 错误，"
        f"{summary['skipped']} 跳过。"
    )
    if options.output_dir is not None:
        print(f"证据报告：{options.output_dir.resolve()}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
