"""Check metric arithmetic and document/chunk evaluation boundaries."""

import math
import unittest

from tools.evaluate_retrieval import evaluate


class RetrievalMetricTests(unittest.TestCase):
    def setUp(self):
        self.judgments = {
            "unit": "document", "coverage": "all_local_documents", "status": "estimated",
            "corpus_documents": [{"document_id": doc} for doc in ("A", "B", "C")],
            "questions": [{"id": "7", "judgments": [
                {"document_id": doc, "grade": grade} for doc, grade in (("A", 2), ("B", 1), ("C", 0))]}]}
        self.payload = {"questions": [{"id": 7, "chunks": [
            {"rank": rank, "chunk_id": f"folder/{doc}.pdf#{local}", "document_id": doc}
            for rank, doc, local in ((3, "A", 1), (1, "B", 0), (2, "A", 0))]}]}

    def test_graded_ndcg_and_both_recall_thresholds(self):
        result = evaluate(self.payload, self.judgments, [1, 2])
        scores = result["questions"][0]["at_document_k"]
        self.assertAlmostEqual(scores["1"]["ndcg"], 1 / 3)
        self.assertEqual(scores["1"]["recall_ge1"], 0.5)
        self.assertEqual(scores["1"]["recall_ge2"], 0)
        self.assertAlmostEqual(scores["2"]["ndcg"], (1 + 3 / math.log2(3)) / (3 + 1 / math.log2(3)))
        self.assertEqual(scores["2"]["recall_ge2"], 1)
        self.assertEqual(scores["2"]["mrr_ge2"], 0.5)

    def test_duplicate_document_not_counted_twice_and_context_coverage_differs(self):
        chunks = self.payload["questions"][0]["chunks"]
        chunks[0]["rank"], chunks[1]["rank"] = 1, 3
        result = evaluate(self.payload, self.judgments, [2])["questions"][0]
        self.assertEqual(result["document_ranking"], ["A", "B"])
        self.assertEqual(result["at_document_k"]["2"]["recall_ge1"], 1)
        self.assertEqual(result["at_chunk_k_document_coverage"]["2"]["recall_ge1"], 0.5)

    def test_notebook_answer_json_uses_chosen_ids_only(self):
        payload = {"answers": [{"id": "7", "chunk_ids": ["nested/A.pdf#42"],
                                "omitted_chunk_ids": ["B.pdf#0"], "answer": "Ignored"}]}
        result = evaluate(payload, self.judgments, [1])
        self.assertEqual(result["questions"][0]["document_ranking"], ["A"])
        self.assertEqual(result["input_type"], "notebook_output_selected_context")

    def test_empty_retrieval_and_no_relevant_documents(self):
        self.payload["questions"][0]["chunks"] = []
        result = evaluate(self.payload, self.judgments, [10])
        self.assertEqual(result["questions"][0]["at_document_k"]["10"]["recall_ge2"], 0)
        for row in self.judgments["questions"][0]["judgments"]:
            row["grade"] = 0
        result = evaluate(self.payload, self.judgments, [10])
        self.assertIsNone(result["questions"][0]["at_document_k"]["10"]["ndcg"])
        self.assertEqual(result["macro_at_document_k"]["10"]["recall_ge2"]["questions"], 0)

    def test_ideal_uses_relevant_documents_missing_from_ranking(self):
        self.payload["questions"][0]["chunks"] = [self.payload["questions"][0]["chunks"][1]]
        result = evaluate(self.payload, self.judgments, [3])["questions"][0]["at_document_k"]["3"]
        self.assertEqual(result["recall_ge1"], 0.5)
        self.assertEqual(result["precision_ge1"], 1 / 3)
        self.assertLess(result["ndcg"], 1)

    def test_unknown_documents_not_silently_assumed_irrelevant(self):
        self.payload["questions"][0]["chunks"][0]["document_id"] = "D"
        with self.assertRaisesRegex(ValueError, "Unjudged"):
            evaluate(self.payload, self.judgments)
        result = evaluate(self.payload, self.judgments, unjudged="zero")
        self.assertEqual(result["questions"][0]["unjudged_documents"], ["D"])

    def test_invalid_and_incomplete_judgments_are_rejected(self):
        self.judgments["questions"][0]["judgments"].pop()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            evaluate(self.payload, self.judgments)
        for bad in (True, 3, -1, 1.5):
            self.judgments["coverage"] = "partial"
            self.judgments["questions"][0]["judgments"][0]["grade"] = bad
            with self.assertRaisesRegex(ValueError, "Grade"):
                evaluate(self.payload, self.judgments)

    def test_duplicate_questions_ranks_and_bad_cutoffs_fail(self):
        with self.assertRaisesRegex(ValueError, "Cutoffs"):
            evaluate(self.payload, self.judgments, [0])
        self.payload["questions"].append(self.payload["questions"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate question"):
            evaluate(self.payload, self.judgments)
        self.payload["questions"].pop()
        self.payload["questions"][0]["chunks"][0]["rank"] = 1
        with self.assertRaisesRegex(ValueError, "ranks"):
            evaluate(self.payload, self.judgments)


if __name__ == "__main__":
    unittest.main()
