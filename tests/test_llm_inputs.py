"""Self-contained exports for external answer generation, without loading models."""

import ast
import json
import tempfile
import unittest
from pathlib import Path

from src.prompts import SYSTEM_PROMPT, USER_MESSAGE_TEMPLATE
from tools.export_llm_inputs import export_llm_inputs


class LLMInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.questions = [{"id": "1", "question": "Quais evidências?", "answer": "GOLD"}]
        self.chunks = [{"chunk_id": f"paper.pdf#{i}", "text": f"Complete evidence {i}\nSecond line",
                        "document_id": "paper", "document": "paper.pdf", "section": "Methods"}
                       for i in range(12)]

    def test_full_text_top_ten_in_rank_order_without_reference_answers(self):
        hits = [{"rank": i + 1, "index": 11 - i, "score": 1 / (i + 1)} for i in range(12)]
        export_llm_inputs(self.root, self.questions, self.chunks,
                          [{"question_id": "1", "variant": "graph", "hits": list(reversed(hits))}])
        payload = json.loads((self.root / "graph.json").read_text())
        chosen = payload["questions"][0]["chunks"]
        self.assertEqual(payload["system_prompt"], SYSTEM_PROMPT)
        self.assertEqual(payload["user_message_template"], USER_MESSAGE_TEMPLATE)
        self.assertEqual(len(chosen), 10)
        self.assertEqual([c["rank"] for c in chosen], list(range(1, 11)))
        self.assertEqual(chosen[0]["text"], self.chunks[11]["text"])
        self.assertEqual(chosen[0]["chunk_id"], "paper.pdf#11")
        self.assertEqual(chosen[0]["document"], "paper.pdf")
        self.assertEqual(chosen[0]["section"], "Methods")
        self.assertNotIn("GOLD", json.dumps(payload))
        self.assertNotIn("answer", payload["questions"][0])

    def test_cases_and_variants_are_isolated_and_indexed(self):
        results = [{"case_id": case, "variant": variant, "question_id": "1",
                    "hits": [{"index": index, "rank": 1}]}
                   for index, (case, variant) in enumerate([
                       ("controls", "dense"), ("case-a", "graph"), ("case-b", "graph")])]
        exported = export_llm_inputs(self.root, self.questions, self.chunks, results)
        self.assertEqual(len(exported), 3)
        for index, record in enumerate(exported):
            payload = json.loads((self.root / record["path"]).read_text())
            self.assertEqual(payload["questions"][0]["chunks"][0]["text"], self.chunks[index]["text"])
        self.assertEqual(json.loads((self.root / "index.json").read_text())["files"], exported)

    def test_empty_ranking_keeps_question(self):
        export_llm_inputs(self.root, self.questions, [], [{"question_id": "1", "variant": "dense", "hits": []}])
        question = json.loads((self.root / "dense.json").read_text())["questions"][0]
        self.assertEqual(question["question"], self.questions[0]["question"])
        self.assertEqual(question["chunks"], [])

    def test_expected_answer_is_exported_when_requested(self):
        export_llm_inputs(self.root, self.questions, [],
                          [{"question_id": "1", "variant": "graph", "hits": []}], include_answers=True)
        question = json.loads((self.root / "graph.json").read_text())["questions"][0]
        self.assertEqual(question["expected_answer"], "GOLD")

    def test_notebook_has_only_unexecuted_code_with_valid_syntax(self):
        notebook = json.loads((Path(__file__).resolve().parents[1] / "notebooks/generation/olmo3_7b_answers.ipynb").read_text())
        sources = []
        for cell in notebook["cells"]:
            self.assertEqual(cell["cell_type"], "code")
            self.assertIsNone(cell["execution_count"])
            self.assertEqual(cell["outputs"], [])
            source = "".join(cell["source"])
            if not source.startswith("%pip"):
                ast.parse(source)
                sources.append(source)
        self.assertIn("allenai/Olmo-3-7B-Instruct", "\n".join(sources))


if __name__ == "__main__":
    unittest.main()
