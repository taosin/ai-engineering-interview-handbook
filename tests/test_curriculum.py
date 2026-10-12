"""Regression checks for editorial reference and schedule contracts."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from curriculum import load_curriculum, validate_curriculum, render_curriculum


class CurriculumTests(unittest.TestCase):
    def setUp(self):
        self.coverage, self.interviews = load_curriculum(ROOT)
        self.questions, self.learning, self.catalog = [json.loads((ROOT / 'data' / (name + '.json')).read_text())
                                                     for name in ('questions', 'learning', 'catalog')]

    def validate(self):
        validate_curriculum(self.coverage, self.interviews, self.questions, self.learning, self.catalog)

    def test_public_plan_is_valid(self):
        self.validate()

    def test_duplicate_pair_cannot_hide_missing_role_module(self):
        self.coverage['requirements'][-1]['module_id'] = self.coverage['requirements'][-2]['module_id']
        with self.assertRaisesRegex(ValueError, 'matrix'):
            self.validate()

    def test_nonexistent_question_and_lab_are_rejected(self):
        for field, value in [('question_ids', ['Q99999']), ('lab_ids', ['L99'])]:
            with self.subTest(field=field):
                data = copy.deepcopy(self.coverage)
                data['requirements'][0][field] = value
                with self.assertRaises(ValueError):
                    validate_curriculum(data, self.interviews, self.questions, self.learning, self.catalog)

    def test_minutes_must_match_without_bool_as_number(self):
        for value in (True, 0, -1, 12):
            with self.subTest(value=value):
                data = copy.deepcopy(self.interviews)
                data['sessions'][0]['blocks'][0]['minutes'] = value
                with self.assertRaises(ValueError):
                    validate_curriculum(self.coverage, data, self.questions, self.learning, self.catalog)

    def test_empty_review_and_provenance_rejected(self):
        self.interviews['sessions'][0]['blocks'][0]['criteria'] = []
        with self.assertRaises(ValueError):
            self.validate()
        self.interviews = load_curriculum(ROOT)[1]
        self.interviews['kind'] = '企业真实试卷'
        with self.assertRaises(ValueError):
            self.validate()

    def test_candidate_views_do_not_disclose_reviewer_followups(self):
        answers = {'answers': []}
        views = render_curriculum(self.coverage, self.interviews, self.questions, self.learning, self.catalog,
                                  answers, lambda f, q: q, lambda f, l: l)
        for session in self.interviews['sessions']:
            role = session['role_id']
            candidate = '\n'.join(views[f'interviews/{role}/candidate.md'])
            reviewer = '\n'.join(views[f'interviews/{role}/reviewer.md'])
            for block in session['blocks']:
                self.assertNotIn(block['follow_up'], candidate)
                self.assertIn(block['follow_up'], reviewer)
        self.assertIn('待补逐题解析', '\n'.join(views['docs/coverage-matrix.md']))


if __name__ == '__main__':
    unittest.main()
