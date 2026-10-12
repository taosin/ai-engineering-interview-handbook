"""Contract and rendering checks for original answers, not semantic grading of prose."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from answers import load_answers, render_answers, validate_answers


class AnswersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_answers(ROOT)
        cls.questions = json.loads((ROOT / 'data/questions.json').read_text(encoding='utf-8'))
        cls.learning = json.loads((ROOT / 'data/learning.json').read_text(encoding='utf-8'))
        cls.catalog = json.loads((ROOT / 'data/catalog.json').read_text(encoding='utf-8'))

    def setUp(self):
        self.data = copy.deepcopy(self.source)

    def validate(self):
        validate_answers(self.data, self.questions, self.learning, self.catalog)

    def rejected(self, mutation, message=None):
        mutation(self.data)
        with self.assertRaisesRegex(ValueError, message or 'Answers:'):
            self.validate()

    def test_real_dataset_and_twelve_selected_questions(self):
        self.validate()
        self.assertEqual({a['question_id'] for a in self.data['answers']}, {
            'Q001', 'Q003', 'Q015', 'Q019', 'Q027', 'Q031',
            'Q035', 'Q041', 'Q044', 'Q049', 'Q050', 'Q102'})

    def test_boolean_schema_is_not_integer_version(self):
        self.rejected(lambda d: d.update(schema_version=True), 'schema version')

    def test_provenance_is_fixed(self):
        self.rejected(lambda d: d.update(kind='面试原答案'), 'provenance')

    def test_future_update_is_rejected(self):
        self.rejected(lambda d: d.update(updated='2099-01-01'), 'future update')

    def test_date_and_future_reference_validation(self):
        for date in ['2026-02-30', '20261012', '2099-01-01']:
            with self.subTest(date=date):
                self.data = copy.deepcopy(self.source)
                self.rejected(lambda d: d['references'][0].update(checked_on=date))

    def test_unknown_question_and_title_drift_are_rejected(self):
        self.rejected(lambda d: d['answers'][0].update(question_id='Q999'), 'unknown question')
        self.data = copy.deepcopy(self.source)
        self.rejected(lambda d: d['answers'][0].update(title='新增另一道题'), 'title differs')

    def test_duplicate_answer_and_output_slug_are_rejected(self):
        self.rejected(lambda d: d['answers'].append(copy.deepcopy(d['answers'][0])), 'duplicate question')
        self.data = copy.deepcopy(self.source)
        self.rejected(lambda d: d['answers'][1].update(slug=d['answers'][0]['slug']), 'duplicate or reserved')

    def test_path_traversal_and_readme_collision_are_rejected(self):
        for slug in ['../outside', '/tmp/output', 'x/y', 'README', 'readme', 'a.md']:
            with self.subTest(slug=slug):
                self.data = copy.deepcopy(self.source)
                self.rejected(lambda d: d['answers'][0].update(slug=slug))

    def test_unsupported_editorial_level_is_rejected(self):
        self.rejected(lambda d: d['answers'][0].update(level='招聘必考'), 'editorial level')

    def test_minimum_explanation_and_followup_depth(self):
        for field in ['deep_dive', 'follow_ups', 'rubric']:
            with self.subTest(field=field):
                self.data = copy.deepcopy(self.source)
                self.rejected(lambda d: d['answers'][0].update({field: d['answers'][0][field][:1]}), 'too few')

    def test_empty_nested_text_is_rejected(self):
        for field, subfield in [('deep_dive', 'body'), ('follow_ups', 'answer'), ('rubric', 'evidence')]:
            with self.subTest(field=field):
                self.data = copy.deepcopy(self.source)
                self.rejected(lambda d: d['answers'][0][field][0].update({subfield: '  '}), 'empty text')

    def test_missing_counterexample_and_empty_exercise_are_rejected(self):
        self.rejected(lambda d: d['answers'][0]['counterexample'].pop('why'), 'missing fields')
        self.data = copy.deepcopy(self.source)
        self.rejected(lambda d: d['answers'][0]['exercise'].update(checks=['one']), 'exercise checks')

    def test_references_cannot_be_empty_unknown_or_duplicated(self):
        for values in [[], ['ARef99'], ['ARef01', 'ARef01']]:
            with self.subTest(values=values):
                self.data = copy.deepcopy(self.source)
                self.rejected(lambda d: d['answers'][0].update(reference_ids=values))

    def test_guide_and_lab_links_must_exist_but_may_be_empty(self):
        self.data['answers'][0].update(guide_ids=[], lab_ids=[])
        self.validate()
        for field, values in [('guide_ids', ['G99']), ('lab_ids', ['L99']), ('guide_ids', ['G01', 'G01'])]:
            with self.subTest(field=field):
                self.data = copy.deepcopy(self.source)
                self.rejected(lambda d: d['answers'][0].update({field: values}))

    def test_reference_urls_require_https_without_credentials(self):
        for url in ['http://example.org/doc', 'https://', 'https://user:secret@example.org/doc', 'https://example.org/with space']:
            with self.subTest(url=url):
                self.data = copy.deepcopy(self.source)
                self.rejected(lambda d: d['references'][0].update(url=url), 'HTTPS')

    def test_duplicate_and_orphan_references_are_rejected(self):
        self.rejected(lambda d: d['references'].append(copy.deepcopy(d['references'][0])), 'duplicate reference id')
        self.data = copy.deepcopy(self.source)
        extra = copy.deepcopy(self.data['references'][0])
        extra.update(id='ARef99', url='https://example.org/orphan')
        self.rejected(lambda d: d['references'].append(extra), 'unreferenced')

    def test_renderer_has_thirteen_views_and_calls_links_from_each_file(self):
        calls = []
        def link(file, identifier):
            calls.append((file, identifier))
            return '[' + identifier + '](reference-' + identifier + '.md)'
        views = render_answers(self.data, link, link, link)
        self.assertEqual(len(views), 13)
        self.assertIn('learning/answers/README.md', views)
        for answer in self.data['answers']:
            file = 'learning/answers/' + answer['slug'] + '.md'
            content = '\n'.join(views[file])
            self.assertIn((file, answer['question_id']), calls)
            self.assertIn('不是面试官原答案', content)
            self.assertIn('不声称学习者已执行或通过', content)
            self.assertIn('难度仅为编者建议', content)
            self.assertIn(answer['counterexample']['why'], content)
            for rid in answer['reference_ids']:
                reference = next(r for r in self.data['references'] if r['id'] == rid)
                self.assertIn(reference['url'], content)

    def test_render_is_deterministic_and_does_not_mutate_data(self):
        before = copy.deepcopy(self.data)
        link = lambda file, identifier: identifier
        self.assertEqual(render_answers(self.data, link, link, link), render_answers(self.data, link, link, link))
        self.assertEqual(self.data, before)


if __name__ == '__main__':
    unittest.main()
