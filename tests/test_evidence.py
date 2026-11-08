"""Evidence extraction and selection regressions; no model calls needed."""
import unittest
from src.evidence import (EvidenceConfig, section_chunks, chunk_sources, content_kind,
                          penalize_order, continuity_order)


class EvidenceTests(unittest.TestCase):
    def test_section_boundary_does_not_leak_overlap_or_merge_short_sections(self):
        chunks = section_chunks('## Methods\n\nMethod evidence.\n\n## References\n\nCitation list.', 800, 150)
        self.assertEqual(len(chunks), 2)
        self.assertNotIn('Method evidence', chunks[1])
        sources = chunk_sources('paper.pdf', chunks)
        self.assertEqual([s['section'] for s in sources], ['Methods', 'References'])
        self.assertNotEqual(sources[0]['section_id'], sources[1]['section_id'])
        self.assertEqual(sources[1]['content_kind'], 'references')

    def test_math_with_blank_lines_is_never_cut_or_duplicated_by_overlap(self):
        formula = '$$\n\\sum_{k=1}^n x_k\n\n= y\n$$'
        chunks = section_chunks('## Proof\n\n' + formula + '\n\nConclusion.', 30, 0)
        self.assertEqual(sum(formula in c for c in chunks), 1)
        self.assertTrue(any('Conclusion.' in c for c in chunks))
        latex = '\\begin{align}\nx &= y\n\n&=z\n\\end{align}'
        self.assertIn(latex, '\n'.join(section_chunks(latex, 20, 0)))

    def test_headings_inside_a_fenced_code_block_do_not_start_sections(self):
        code = '```python\n# A comment\n\nvalue = 1\n```'
        self.assertEqual(section_chunks(code, 100, 0), [code])

    def test_sources_inherit_hierarchy_and_distinguish_same_named_sections(self):
        chunks = ['# Paper', '## Results', '### Proof\n\nA', 'B', '## Discussion', '### Proof\n\nC']
        sources = chunk_sources('paper.pdf', chunks)
        self.assertEqual(sources[3]['section_path'], ['Paper', 'Results', 'Proof'])
        self.assertNotEqual(sources[2]['section_id'], sources[5]['section_id'])
        self.assertEqual(sources[5]['local_chunk_index'], 5)

    def test_front_matter_detection_keeps_real_abstracts_and_body_text(self):
        self.assertEqual(content_kind('# Paper title\n\nAuthors, University of Example. a@b.edu', 'Paper title', 0), 'front_matter')
        self.assertEqual(content_kind('## Abstract\n\nWe prove a new theorem.', 'Abstract', 0), 'body')
        self.assertEqual(content_kind('The university experiment measured nitrogen at 500 C. '*20, 'Introduction', 0), 'body')
        self.assertEqual(content_kind('A method discusses references to other work.', 'Methods', 4), 'body')

    def test_penalties_reduce_scores_without_deleting_candidates(self):
        sources = [{'content_kind': k} for k in ['references', 'front_matter', 'body']]
        order, scores = penalize_order([0, 1, 2], {0: 1., 1: 1., 2: .8}, sources, 'What is the method?')
        self.assertEqual(order, [2, 1, 0])
        self.assertAlmostEqual(scores[0], .5)
        self.assertAlmostEqual(scores[1], .7)
        self.assertEqual(set(order), {0, 1, 2})
        _, scores = penalize_order([0, 1], {0: 1., 1: 1.}, sources, 'Who are the authors and which references are cited?')
        self.assertEqual(scores, {0: 1., 1: 1.})

    def test_continuity_stays_in_section_and_document_and_deduplicates(self):
        sources = chunk_sources('a.pdf', ['## Proof', 'A', 'B', '## References', 'C'])
        sources += chunk_sources('b.pdf', ['## Proof', 'D'])
        selected = continuity_order([1, 2, 6, 3], sources, EvidenceConfig(max_chunks=10))
        self.assertEqual(selected, [0, 1, 2, 5, 6, 3, 4])
        self.assertEqual(len(selected), len(set(selected)))
        self.assertEqual(continuity_order([1], sources), [0, 1, 2])

    def test_large_section_window_limits_count_and_retains_anchor(self):
        sources = chunk_sources('a.pdf', ['## Proof'] + [str(i) for i in range(20)])
        config = EvidenceConfig(neighbors_before=1, neighbors_after=3, max_chunks=3)
        chosen = continuity_order([10], sources, config)
        self.assertIn(10, chosen)
        self.assertEqual(len(chosen), 3)
        self.assertTrue(all(9 <= i <= 13 for i in chosen))

    def test_no_expansion_for_missing_section_and_invalid_config_rejected(self):
        sources = chunk_sources('a.pdf', ['No heading', 'Continuation'])
        self.assertEqual(continuity_order([1], sources), [1])
        for kw in [{'reference_weight': 0}, {'front_matter_weight': float('nan')}, {'neighbors_after': -1}, {'max_chunks': 0}]:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                EvidenceConfig(**kw)


if __name__ == '__main__':
    unittest.main()
