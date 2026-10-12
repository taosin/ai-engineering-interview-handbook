"""Behavior checks and per-case evidence for L04; fixtures are synthetic."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json
import unittest

from evaluation import InputError, evaluate, fixture, loads_document, nearest_rank


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture()
        self.evidence = {}

    def rejected(self, document, expected_fragment):
        try:
            evaluate(document)
        except InputError as exc:
            self.assertIn(expected_fragment, str(exc))
            self.evidence = {"expected": {"rejected": True, "reason_contains": expected_fragment},
                             "input": document, "actual_error": str(exc)}
        else:
            self.fail("invalid input was accepted")

    def test_00_wrong_report_and_correct_result(self):
        """Reproduce 7/7 and dropped retry cost, then recover paired 6/8 and three failed gates."""
        result = evaluate(self.data)
        wrong = result["intentionally_wrong_control"]["candidate"]
        self.assertEqual((wrong["wrong_goal_or_model_successes"], wrong["wrong_completed_only_denominator"]), (7, 7))
        self.assertEqual(wrong["wrong_last_attempt_only_cost"], 16)
        self.assertEqual(wrong["wrong_completed_only_p95"]["value_ms"], 180)
        for role, cost, latency in (("baseline", 16, 300), ("candidate", 20, 400)):
            run = result[role]
            self.assertEqual((run["successes"], run["denominator"], run["success_rate_percent"]), (6, 8, 75))
            self.assertEqual(run["total_cost"], cost)
            self.assertEqual((run["p95"]["rank"], run["p95"]["value_ms"]), (8, latency))
        self.assertEqual(result["cost_increase_percent"], 25)
        self.assertFalse(result["candidate_passes"])
        self.assertEqual(result["failed_gates"], ["zero_forbidden_effects", "cost_at_most_110_percent", "p95_at_most_110_percent"])
        self.evidence = {"expected": {"actual_success": "6/8 each", "cost": [16, 20], "p95_ms": [300, 400],
                                      "candidate_passes": False, "wrong_candidate": "7/7; last-attempt cost 16"},
                         "input": self.data, "actual": result}

    def test_01_model_pass_cannot_override_duplicate_effect(self):
        """The candidate case-7 model pass remains visible but cannot erase its deterministic failure."""
        case = evaluate(self.data)["candidate"]["cases"][6]
        self.assertEqual(case["model_judgment"], "pass")
        self.assertTrue(case["goal_achieved"])
        self.assertFalse(case["success"])
        self.assertEqual(case["failure_reasons"], ["forbidden_side_effect"])
        self.evidence = {"expected": {"success": False}, "actual": case}

    def test_02_timeout_includes_all_attempt_cost_and_latency(self):
        """A timed-out task still contributes to the denominator, both costs and endpoint latency."""
        case = evaluate(self.data)["candidate"]["cases"][7]
        self.assertEqual((case["attempt_count"], case["total_cost"], case["latency_ms"]), (2, 3, 400))
        self.assertEqual(case["failure_reasons"], ["timed_out", "goal_not_achieved"])
        self.evidence = {"expected": {"attempts": 2, "cost": 3, "latency_ms": 400}, "actual": case}

    def test_03_missing_final_rejected(self):
        """A missing final row cannot silently shrink the denominator."""
        self.data["runs"]["candidate"]["finals"].pop()
        self.rejected(self.data, "exactly eight")

    def test_04_duplicate_final_rejected_even_at_eight_rows(self):
        """Replacing a task with a duplicate preserves row count but is still rejected."""
        rows = self.data["runs"]["baseline"]["finals"]
        rows[-1] = deepcopy(rows[0])
        self.rejected(self.data, "duplicate final")

    def test_05_extra_final_rejected(self):
        """An extra duplicate final row is not a ninth task."""
        self.data["runs"]["candidate"]["finals"].append(deepcopy(self.data["runs"]["candidate"]["finals"][0]))
        self.rejected(self.data, "exactly eight")

    def test_06_unknown_final_case_rejected(self):
        """An unrelated task cannot replace a missing paired task."""
        self.data["runs"]["candidate"]["finals"][0]["case_id"] = "case-99"
        self.rejected(self.data, "unknown final case")

    def test_07_mixed_final_version_rejected(self):
        """A final from a different implementation version is rejected."""
        self.data["runs"]["candidate"]["finals"][0]["version"] = "baseline-v1"
        self.rejected(self.data, "mixed final version")

    def test_08_mixed_attempt_version_rejected(self):
        """Every retry must belong to the same implementation version."""
        self.data["runs"]["candidate"]["attempts"][4]["version"] = "candidate-v2"
        self.rejected(self.data, "mixed attempt version")

    def test_09_run_version_rejected(self):
        """The run version cannot be changed without the exercise contract."""
        self.data["runs"]["candidate"]["version"] = "candidate-v2"
        self.rejected(self.data, "wrong run version")

    def test_10_manifest_change_rejected(self):
        """Dropping a failed task from the manifest cannot redefine this experiment."""
        self.data["manifest"]["case_ids"].pop()
        self.rejected(self.data, "manifest differs")

    def test_11_missing_attempt_rejected(self):
        """Dropping an earlier retry is rejected even if all final rows remain."""
        self.data["runs"]["candidate"]["attempts"].pop(4)
        self.rejected(self.data, "missing/extra attempt")

    def test_12_duplicate_attempt_rejected_at_expected_count(self):
        """An attempt duplicate cannot fill the slot of another attempt."""
        attempts = self.data["runs"]["candidate"]["attempts"]
        attempts[-1] = deepcopy(attempts[-2])
        self.rejected(self.data, "duplicate or invalid attempt identity")

    def test_13_retry_sequence_gap_rejected(self):
        """An ordinal gap is rejected rather than treating the latest event as the entire run."""
        self.data["runs"]["candidate"]["attempts"][-1]["ordinal"] = 3
        self.rejected(self.data, "invalid attempt ordinal")

    def test_14_false_attempt_count_rejected(self):
        """A final row cannot pretend a two-attempt allocation had only one call."""
        self.data["runs"]["candidate"]["finals"][4]["attempt_count"] = 1
        self.rejected(self.data, "incomplete attempt sequence")

    def test_15_abnormal_numeric_values_rejected(self):
        """Negative, boolean, string, nonfinite and unbounded measures cannot produce a score."""
        observations = []
        for value in (-1, True, "2", float("nan"), float("inf"), float("-inf"), 10**13):
            with self.subTest(value=repr(value)):
                data = fixture(); data["runs"]["candidate"]["attempts"][0]["cost"] = value
                with self.assertRaises(InputError) as caught:
                    evaluate(data)
                observations.append({"injected_value": repr(value), "error": str(caught.exception)})
        self.evidence = {"expected": {"all_rejected": True}, "actual": observations}

    def test_16_final_latency_cannot_drop_first_attempt(self):
        """An endpoint duration less than the summed attempts is rejected."""
        self.data["runs"]["candidate"]["finals"][4]["latency_ms"] = 110
        self.rejected(self.data, "omits attempt time")

    def test_17_timeout_cannot_claim_goal_achieved(self):
        """A timed-out attempt cannot silently claim a verified goal."""
        self.data["runs"]["candidate"]["attempts"][-1]["goal_achieved"] = True
        self.rejected(self.data, "unconfirmed outcome")

    def test_18_final_cannot_override_attempt_goal(self):
        """The final goal must agree with the terminal attempt evidence."""
        self.data["runs"]["baseline"]["finals"][2]["goal_achieved"] = True
        self.rejected(self.data, "final disagrees")

    def test_19_prior_attempt_effect_cannot_be_dropped(self):
        """A side effect from an earlier attempt must survive into the final ledger."""
        self.data["runs"]["candidate"]["attempts"][4]["forbidden_effects"] = 1
        self.rejected(self.data, "drops/adds forbidden effects")

    def test_20_claimed_success_cannot_override_evidence(self):
        """Unlike a non-authoritative judge note, a contradictory success claim invalidates input."""
        self.data["runs"]["candidate"]["finals"][6]["claimed_success"] = True
        self.rejected(self.data, "claimed success contradicts")

    def test_21_types_and_unknown_fields_rejected(self):
        """Goals, counts, schemas and fields are typed rather than coerced."""
        observations = []
        mutations = [lambda d: d.update(schema_version=True),
                     lambda d: d["runs"]["baseline"]["finals"][0].update(goal_achieved=1),
                     lambda d: d["runs"]["baseline"]["finals"][0].update(forbidden_effects=False),
                     lambda d: d["runs"]["baseline"]["finals"][0].update(attempt_count=1.0),
                     lambda d: d.update(overall_grade=100)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                data = fixture(); mutate(data)
                with self.assertRaises(InputError) as caught: evaluate(data)
                observations.append({"mutation_index": index, "error": str(caught.exception)})
        self.evidence = {"expected": {"all_rejected": True}, "actual": observations}

    def test_22_json_duplicate_keys_and_nonfinite_literals_rejected(self):
        """JSON parsing rejects overwritten keys, NaN/Infinity, excessive size and malformed input."""
        observations = []
        for encoded in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{', ' ' * (1024 * 1024 + 1)):
            with self.subTest(prefix=encoded[:30]):
                with self.assertRaises(InputError) as caught: loads_document(encoded)
                observations.append({"prefix": encoded[:30], "bytes": len(encoded), "error": str(caught.exception)})
        self.evidence = {"expected": {"all_rejected": True}, "actual": observations}

    def test_23_nearest_rank_explicit_sample_and_invalid_inputs(self):
        """The p95 rank includes the eighth timeout, rather than interpolating or dropping it."""
        values = [400, 100, 180, 110, 160, 120, 150, 130]
        result = nearest_rank(values)
        self.assertEqual(result["rank"], 8); self.assertEqual(result["value_ms"], 400)
        self.assertEqual(nearest_rank([7])["value_ms"], 7)
        for bad in ([], [True], [-1], [float("nan")]):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(InputError): nearest_rank(bad)
        with self.assertRaises(InputError): nearest_rank([1], Decimal(0))
        self.evidence = {"expected": {"rank": 8, "p95_ms": 400}, "input": values, "actual": result}

    def test_24_row_order_does_not_change_pairing_and_input_is_unchanged(self):
        """Task and attempt order do not alter results; the calculator does not mutate evidence."""
        expected = evaluate(self.data)
        for run in self.data["runs"].values(): run["finals"].reverse(); run["attempts"].reverse()
        before = deepcopy(self.data)
        actual = evaluate(self.data)
        self.assertEqual(actual, expected); self.assertEqual(self.data, before)
        self.evidence = {"expected": {"order_independent": True, "no_mutation": True},
                         "actual_case_order": [c["case_id"] for c in actual["candidate"]["cases"]]}

    def test_25_gate_boundary_and_real_passing_control(self):
        """Exactly 110 percent is accepted when deterministic failures are absent; any excess fails."""
        candidate = self.data["runs"]["candidate"]
        for final in candidate["finals"]: final["forbidden_effects"] = 0
        for attempt in candidate["attempts"]:
            attempt["forbidden_effects"] = 0
            attempt["cost"] = 2 if attempt["case_id"] in ("case-1", "case-2", "case-3", "case-4") else 1.2
        candidate["finals"][-1]["latency_ms"] = 330
        candidate["attempts"][-1]["duration_ms"] = 290
        passing = evaluate(self.data)
        self.assertEqual(passing["candidate"]["total_cost"], 17.6)
        self.assertTrue(passing["candidate_passes"])
        candidate["attempts"][0]["cost"] = 2.000001
        failing = evaluate(self.data)
        self.assertEqual(failing["failed_gates"], ["cost_at_most_110_percent"])
        self.evidence = {"expected": {"equal_boundary_passes": True, "cost_excess_fails": True},
                         "actual_boundary_gates": passing["gates"], "actual_excess_gates": failing["gates"]}

    def test_26_zero_baseline_has_explicit_undefined_relative_growth(self):
        """A zero baseline does not divide by zero or manufacture a relative percentage."""
        for attempt in self.data["runs"]["baseline"]["attempts"]: attempt["cost"] = 0
        result = evaluate(self.data)
        self.assertIsNone(result["cost_increase_percent"])
        self.assertTrue(result["zero_baseline_cost_note"])
        self.assertFalse(result["gates"]["cost_at_most_110_percent"]["passed"])
        self.evidence = {"expected": {"relative_growth": None, "cost_gate": False},
                         "actual": {k: result[k] for k in ("cost_increase_percent", "zero_baseline_cost_note", "gates")}}

    def test_27_json_round_trip_and_fixture_isolation(self):
        """Independent copies and JSON input retain the same full paired calculation."""
        encoded = json.dumps(self.data)
        actual = evaluate(loads_document(encoded))
        self.assertEqual(actual, evaluate(fixture()))
        other = fixture(); other["manifest"]["case_ids"].pop()
        self.assertEqual(len(fixture()["manifest"]["case_ids"]), 8)
        self.evidence = {"expected": {"same_results": True, "fresh_fixture_cases": 8},
                         "actual_success_counts": [actual[r]["successes"] for r in ("baseline", "candidate")]}


if __name__ == "__main__":
    unittest.main()
