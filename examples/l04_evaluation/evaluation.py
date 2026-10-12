"""Strict, offline evaluation of the fixed L04 synthetic experiment.

The manifest and attempt allocation are exercise contracts, not inferred from
whichever successful rows happen to be present. No model or network is used.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_CEILING
import json
import math
from pathlib import Path

CASE_IDS = tuple(f"case-{i}" for i in range(1, 9))
VERSIONS = {"baseline": "baseline-v1", "candidate": "candidate-v1"}
MANIFEST = {
    "id": "l04-eight-cases", "version": "1",
    "case_ids": list(CASE_IDS), "cost_unit": "synthetic-unit", "latency_unit": "ms",
}
MAX_INPUT_BYTES = 1024 * 1024
MAX_MEASURE = Decimal("1000000000000")
RATIO_LIMIT = Decimal("1.10")


class InputError(ValueError):
    """The evidence does not satisfy the fixed experiment contract."""


def require(condition, message):
    if not condition:
        raise InputError(message)


def fields(value, required, optional=(), label="object"):
    require(type(value) is dict, f"{label}: expected object")
    require(set(required) <= set(value), f"{label}: missing fields")
    require(set(value) <= set(required) | set(optional), f"{label}: unexpected fields")


def number(value, label):
    require(type(value) in (int, float), f"{label}: expected a numeric value, not bool/string")
    require(not isinstance(value, float) or math.isfinite(value), f"{label}: nonfinite value")
    result = Decimal(str(value))
    require(0 <= result <= MAX_MEASURE, f"{label}: outside 0..1e12")
    return result


def integer(value, label, maximum=32):
    require(type(value) is int and 0 <= value <= maximum, f"{label}: invalid integer")
    return value


def numeric(value):
    """JSON-friendly output; comparisons use Decimal before this conversion."""
    return int(value) if value == value.to_integral_value() else float(value)


def nearest_rank(values, percentile=Decimal("0.95")):
    require(type(values) is list and values, "percentile: empty/non-list sample")
    require(isinstance(percentile, Decimal) and percentile.is_finite()
            and 0 < percentile <= 1, "percentile: expected Decimal in (0,1]")
    ordered = sorted(number(value, "latency") for value in values)
    rank = int((percentile * len(ordered)).to_integral_value(rounding=ROUND_CEILING))
    return {"method": "nearest-rank", "percentile": str(percentile),
            "n": len(ordered), "rank": rank, "value_ms": numeric(ordered[rank - 1])}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"JSON: duplicate key {key}")
        result[key] = value
    return result


def loads_document(encoded):
    require(type(encoded) is str and len(encoded.encode("utf-8")) <= MAX_INPUT_BYTES,
            "JSON: input exceeds 1 MiB or is not text")
    def invalid_constant(value):
        raise InputError(f"JSON: nonfinite constant {value}")
    try:
        return json.loads(encoded, object_pairs_hook=_unique_object,
                          parse_constant=invalid_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise InputError("JSON: invalid or too deeply nested input") from exc


def load_document(path):
    path = Path(path)
    require(path.stat().st_size <= MAX_INPUT_BYTES, "JSON: input exceeds 1 MiB")
    return loads_document(path.read_text(encoding="utf-8"))


def _version_run(run, role):
    version = VERSIONS[role]
    fields(run, ("version", "finals", "attempts"), label=role)
    require(run["version"] == version, f"{role}: wrong run version")
    require(type(run["finals"]) is list and len(run["finals"]) == 8,
            f"{role}: expected exactly eight final records")
    expected_attempts = {case_id: (2 if role == "candidate" and i >= 5 else 1)
                         for i, case_id in enumerate(CASE_IDS, 1)}
    require(type(run["attempts"]) is list
            and len(run["attempts"]) == sum(expected_attempts.values()),
            f"{role}: missing/extra attempt records against fixed allocation")
    grouped = defaultdict(dict)
    attempt_ids = set()
    for attempt in run["attempts"]:
        fields(attempt, ("attempt_id", "case_id", "version", "ordinal", "outcome",
                         "goal_achieved", "forbidden_effects", "cost", "duration_ms"), label="attempt")
        cid = attempt["case_id"]
        require(type(cid) is str and cid in CASE_IDS, f"{role}: unknown attempt case")
        require(attempt["version"] == version, f"{role}/{cid}: mixed attempt version")
        ordinal = integer(attempt["ordinal"], "attempt ordinal")
        require(1 <= ordinal <= expected_attempts[cid], f"{role}/{cid}: invalid attempt ordinal")
        aid = attempt["attempt_id"]
        require(aid == f"{version}:{cid}:{ordinal}" and aid not in attempt_ids,
                f"{role}/{cid}: duplicate or invalid attempt identity")
        require(ordinal not in grouped[cid], f"{role}/{cid}: duplicate attempt ordinal")
        attempt_ids.add(aid)
        require(attempt["outcome"] in ("completed", "timed_out", "error"), f"{aid}: invalid outcome")
        require(type(attempt["goal_achieved"]) is bool, f"{aid}: goal must be boolean")
        require(attempt["outcome"] == "completed" or not attempt["goal_achieved"],
                f"{aid}: unconfirmed outcome cannot claim goal achieved")
        integer(attempt["forbidden_effects"], "attempt forbidden effects", maximum=1000000)
        number(attempt["cost"], "attempt cost")
        number(attempt["duration_ms"], "attempt duration")
        grouped[cid][ordinal] = attempt
    finals = {}
    for final in run["finals"]:
        fields(final, ("case_id", "version", "status", "goal_achieved", "forbidden_effects",
                       "latency_ms", "attempt_count"), ("model_judgment", "claimed_success"), "final")
        cid = final["case_id"]
        require(type(cid) is str and cid in CASE_IDS, f"{role}: unknown final case")
        require(cid not in finals, f"{role}/{cid}: duplicate final record")
        require(final["version"] == version, f"{role}/{cid}: mixed final version")
        require(final["status"] in ("completed", "timed_out", "error"), f"{role}/{cid}: invalid final status")
        require(type(final["goal_achieved"]) is bool, f"{role}/{cid}: goal must be boolean")
        effects = integer(final["forbidden_effects"], "final forbidden effects", maximum=1000000)
        count = integer(final["attempt_count"], "final attempt count")
        require(count == expected_attempts[cid] and set(grouped[cid]) == set(range(1, count + 1)),
                f"{role}/{cid}: incomplete attempt sequence")
        attempts = [grouped[cid][i] for i in range(1, count + 1)]
        last = attempts[-1]
        require(final["status"] == last["outcome"] and final["goal_achieved"] == last["goal_achieved"],
                f"{role}/{cid}: final disagrees with last attempt")
        require(effects == sum(a["forbidden_effects"] for a in attempts),
                f"{role}/{cid}: final drops/adds forbidden effects")
        elapsed = number(final["latency_ms"], "end-to-end latency")
        require(elapsed >= sum((number(a["duration_ms"], "attempt duration") for a in attempts), Decimal(0)),
                f"{role}/{cid}: end-to-end latency omits attempt time")
        if "model_judgment" in final:
            require(final["model_judgment"] in ("pass", "fail", "unknown"), f"{role}/{cid}: invalid model judgment")
        success = final["status"] == "completed" and final["goal_achieved"] and effects == 0
        if "claimed_success" in final:
            require(type(final["claimed_success"]) is bool and final["claimed_success"] == success,
                    f"{role}/{cid}: claimed success contradicts deterministic evidence")
        failures = []
        if final["status"] != "completed":
            failures.append(final["status"])
        if not final["goal_achieved"]:
            failures.append("goal_not_achieved")
        if effects:
            failures.append("forbidden_side_effect")
        finals[cid] = {"case_id": cid, "version": version, "status": final["status"],
                       "goal_achieved": final["goal_achieved"], "forbidden_effects": effects,
                       "success": success, "failure_reasons": failures,
                       "attempt_count": count,
                       "total_cost": numeric(sum((number(a["cost"], "cost") for a in attempts), Decimal(0))),
                       "latency_ms": numeric(elapsed), "attempts": attempts,
                       "model_judgment": final.get("model_judgment", "not_recorded"),
                       "model_judgment_is_authoritative": False}
    require(set(finals) == set(CASE_IDS), f"{role}: missing final case")
    cases = [finals[cid] for cid in CASE_IDS]
    total_cost = sum((number(attempt["cost"], "cost") for attempt in run["attempts"]), Decimal(0))
    successes = sum(case["success"] for case in cases)
    return {"version": version, "denominator": len(CASE_IDS), "successes": successes,
            "success_rate_percent": 100 * successes / len(CASE_IDS),
            "total_cost": numeric(total_cost), "cost_unit": MANIFEST["cost_unit"],
            "forbidden_effects": sum(case["forbidden_effects"] for case in cases),
            "timeouts": sum(case["status"] == "timed_out" for case in cases),
            "p95": nearest_rank([case["latency_ms"] for case in cases]), "cases": cases}


def evaluate(document):
    fields(document, ("schema_version", "manifest", "runs"), label="document")
    require(type(document["schema_version"]) is int and document["schema_version"] == 1, "unsupported schema")
    require(document["manifest"] == MANIFEST, "manifest differs from fixed L04 allocation/units")
    fields(document["runs"], ("baseline", "candidate"), label="runs")
    baseline = _version_run(document["runs"]["baseline"], "baseline")
    candidate = _version_run(document["runs"]["candidate"], "candidate")
    base_cost, cand_cost = (sum((number(a["cost"], "cost") for a in document["runs"][role]["attempts"]), Decimal(0))
                            for role in ("baseline", "candidate"))
    base_p95, cand_p95 = (Decimal(str(run["p95"]["value_ms"])) for run in (baseline, candidate))
    gates = {
        "success_rate_not_lower": {"passed": candidate["successes"] >= baseline["successes"],
                                   "baseline": baseline["success_rate_percent"], "candidate": candidate["success_rate_percent"]},
        "zero_forbidden_effects": {"passed": candidate["forbidden_effects"] == 0, "maximum": 0,
                                   "candidate": candidate["forbidden_effects"]},
        "cost_at_most_110_percent": {"passed": cand_cost <= base_cost * RATIO_LIMIT,
                                     "maximum": numeric(base_cost * RATIO_LIMIT), "candidate": numeric(cand_cost)},
        "p95_at_most_110_percent": {"passed": cand_p95 <= base_p95 * RATIO_LIMIT,
                                    "maximum_ms": numeric(base_p95 * RATIO_LIMIT), "candidate_ms": numeric(cand_p95)},
    }
    # A deliberately wrong control, calculated from the same validated raw rows.
    # This is not another supported scoring mode and cannot decide the release.
    wrong = {}
    for role in VERSIONS:
        run = document["runs"][role]
        completed = [row for row in run["finals"] if row["status"] == "completed"]
        model_success = sum(row["goal_achieved"] or row.get("model_judgment") == "pass" for row in completed)
        last = {row["case_id"]: max((a for a in run["attempts"] if a["case_id"] == row["case_id"]),
                                  key=lambda a: a["ordinal"]) for row in run["finals"]}
        wrong[role] = {"wrong_completed_only_denominator": len(completed),
                       "wrong_goal_or_model_successes": model_success,
                       "wrong_success_rate_percent": None if not completed else 100 * model_success / len(completed),
                       "wrong_last_attempt_only_cost": numeric(sum((number(a["cost"], "cost") for a in last.values()), Decimal(0))),
                       "wrong_completed_only_p95": nearest_rank([row["latency_ms"] for row in completed]) if completed else None}
    return {"manifest": dict(MANIFEST), "baseline": baseline, "candidate": candidate,
            "cost_increase_percent": numeric((cand_cost - base_cost) * 100 / base_cost) if base_cost else None,
            "zero_baseline_cost_note": None if base_cost else "Relative cost growth is undefined; compare absolute gate instead.",
            "gates": gates, "candidate_passes": all(item["passed"] for item in gates.values()),
            "failed_gates": [name for name, item in gates.items() if not item["passed"]],
            "intentionally_wrong_control": {"warning": "Incorrect statistics reproduced for comparison; never a passing result.", **wrong}}


def fixture():
    """Fresh public synthetic records matching every numeric condition in L04."""
    goals = {"baseline": [True, True, False, True, True, True, True, False],
             "candidate": [True, True, True, True, True, True, True, False]}
    latencies = {"baseline": [100, 120, 130, 150, 160, 170, 200, 300],
                 "candidate": [100, 110, 120, 130, 150, 160, 180, 400]}
    document = {"schema_version": 1, "manifest": {**MANIFEST, "case_ids": list(CASE_IDS)}, "runs": {}}
    for role, version in VERSIONS.items():
        run = {"version": version, "finals": [], "attempts": []}
        for i, cid in enumerate(CASE_IDS):
            costs = [1, 2] if role == "candidate" and i >= 4 else [2]
            status = "timed_out" if i == 7 else "completed"
            effects = 1 if role == "candidate" and i == 6 else 0
            final = {"case_id": cid, "version": version, "status": status, "goal_achieved": goals[role][i],
                     "forbidden_effects": effects, "latency_ms": latencies[role][i], "attempt_count": len(costs)}
            if role == "candidate" and i == 6:
                final["model_judgment"] = "pass"
            run["finals"].append(final)
            for ordinal, cost in enumerate(costs, 1):
                last = ordinal == len(costs)
                run["attempts"].append({"attempt_id": f"{version}:{cid}:{ordinal}", "case_id": cid,
                                        "version": version, "ordinal": ordinal,
                                        "outcome": status if last else "error",
                                        "goal_achieved": goals[role][i] if last else False,
                                        "forbidden_effects": effects if last else 0, "cost": cost,
                                        "duration_ms": latencies[role][i] - (40 if len(costs) == 2 else 0) if last else 40})
        document["runs"][role] = run
    return document


def main(argv=None):
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="按固定 L04 合同计算原始 JSON；不运行模型")
    parser.add_argument("input", nargs="?", type=Path, help="省略时计算内置合成夹具")
    args = parser.parse_args(argv)
    try:
        document = load_document(args.input) if args.input else fixture()
        result = evaluate(document)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (InputError, OSError, UnicodeError) as exc:
        print(f"评测输入被拒绝：{exc}", file=sys.stderr)
        return 2
    # Candidate rejection is the correct evaluation result, not a calculator error.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
