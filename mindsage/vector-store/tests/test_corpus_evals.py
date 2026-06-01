import importlib.util
import json
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1] / "mcp_vector_store"
sys.path.insert(0, str(MODULE_DIR))

CORPUS_EVALS_PATH = MODULE_DIR / "corpus_evals.py"
SPEC = importlib.util.spec_from_file_location("corpus_evals", CORPUS_EVALS_PATH)
corpus_evals = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corpus_evals)

run_fixture_corpus_evals = corpus_evals.run_fixture_corpus_evals
format_corpus_eval_report = corpus_evals.format_corpus_eval_report


class CorpusEvalsTest(unittest.TestCase):
    def test_run_fixture_corpus_evals_returns_passing_summary(self):
        report = run_fixture_corpus_evals()

        self.assertEqual(report["summary"]["total"], 4)
        self.assertEqual(report["summary"]["passed"], 4)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["score"], 1.0)
        self.assertGreaterEqual(report["corpus"]["document_count"], 25)
        self.assertGreater(report["corpus"]["word_count"], 10000)
        self.assertEqual(
            {case["id"] for case in report["cases"]},
            {
                "corpus.named_thing_travel",
                "corpus.cross_source_provider",
                "corpus.financial_pii_safety",
                "corpus.medical_allergy_lookup",
            },
        )

    def test_fixture_corpus_eval_report_omits_sensitive_fixture_values(self):
        report_json = json.dumps(run_fixture_corpus_evals())

        self.assertNotIn("don.jones.1987@gmail.com", report_json)
        self.assertNotIn("(408) 555-7834", report_json)
        self.assertNotIn("4521-8834-9912", report_json)
        self.assertNotIn("542871987", report_json)
        self.assertNotIn("XXX-XX-4829", report_json)

    def test_format_corpus_eval_report_is_stable_and_human_readable(self):
        output = format_corpus_eval_report(run_fixture_corpus_evals())

        self.assertIn("MindSage fixture corpus evals: 4/4 passed", output)
        self.assertIn("PASS corpus.named_thing_travel", output)
        self.assertIn("PASS corpus.cross_source_provider", output)
        self.assertIn("PASS corpus.financial_pii_safety", output)


if __name__ == "__main__":
    unittest.main()
