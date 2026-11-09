"""Integrity of the public development set, independent of models and generated PDFs."""

import hashlib
import json
import unittest
from pathlib import Path

from tools.evaluate_retrieval import load_judgments

ROOT = Path(__file__).resolve().parents[1]


class PublicEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = ROOT / "data/local_eval"
        cls.judgments = json.loads((ROOT / "experiments/judgments/public-25-2026-11-08.json").read_text())
        cls.catalog = {d["document_id"]: d for d in cls.judgments["corpus_documents"]}
        cls.evidence = [json.loads(line) for line in (cls.base / "evidence.jsonl").read_text().splitlines()]

    def test_original_questions_and_answers_preserved(self):
        source = ROOT / "starter-kit/IEEE-CIS-DSQA-Starter-Kit/sample/sample_qa.json"
        official = json.loads(source.read_text())
        self.assertEqual(json.loads((self.base / "questions.json").read_text()), official)
        self.assertEqual({str(q["id"]) for q in official}, {str(i) for i in range(1, 26)})
        self.assertEqual(self.judgments["reference_questions_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        for expected, annotated in zip(official, self.judgments["questions"]):
            self.assertEqual(annotated["id"], str(expected["id"]))
            self.assertEqual(annotated["question"], expected["question"])
            self.assertEqual(annotated["expected_answer"], expected["answer"])

    def test_full_grade_matrix_is_accepted_by_existing_metric_loader(self):
        qrels = load_judgments(self.judgments)
        self.assertEqual(len(qrels), 25)
        self.assertEqual(sum(len(rows) for rows in qrels.values()), 25 * len(self.catalog))
        self.assertEqual(self.judgments["status"], "assistant_estimate")
        for q in self.judgments["questions"]:
            positives = [j for j in q["judgments"] if j["grade"] > 0]
            self.assertTrue(all(j["evidence"] for j in positives))
            if q["coverage_status"] == "missing_source":
                self.assertFalse(any(j["grade"] == 2 for j in positives))
            if q["coverage_status"] == "supported_text":
                self.assertTrue(any(j["grade"] == 2 for j in positives))
            if q["coverage_status"] == "requires_figure":
                self.assertTrue(any(e["modality"] == "figure" and e["pdf_pages"]
                                    for j in positives for e in j["evidence"]))

    def test_passages_have_stable_source_identity_and_exact_excerpt_hash(self):
        identities = [e["evidence_id"] for e in self.evidence]
        self.assertEqual(len(identities), len(set(identities)))
        embedded = [e for q in self.judgments["questions"] for j in q["judgments"] for e in j["evidence"]]
        self.assertEqual(self.evidence, embedded)
        for e in self.evidence:
            source = self.catalog[e["document_id"]]
            self.assertEqual(e["end_char"] - e["start_char"], len(e["excerpt"]))
            self.assertEqual(e["excerpt_sha256"], hashlib.sha256(e["excerpt"].encode()).hexdigest())
            for key in ("markdown", "markdown_sha256", "pdf_path", "pdf_sha256"):
                self.assertEqual(e[key], source[key])
            self.assertTrue(all(1 <= page <= source["pages"] for page in e["pdf_pages"]))

    def test_experiment_configuration_freezes_the_judged_corpus(self):
        config = json.loads((ROOT / "experiments/configs/public-25.json").read_text())
        self.assertEqual(config["question_ids"], list(range(1, 26)))
        self.assertEqual(set(config["document_ids"]), set(self.catalog))
        self.assertEqual(config["questions"], "data/local_eval/questions.json")
        for line in (ROOT / "data/download_pdfs/public_qa_expansion/documents.jsonl").read_text().splitlines():
            self.assertLessEqual(set(json.loads(line)), {"id", "title", "domain", "article_url", "pdf_url"})


if __name__ == "__main__":
    unittest.main()
