"""Behavioral tests for bounded, traceable graph-assisted corpus retrieval."""

import math
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from src.kg_retrieval import EntityMatcher, GraphConfig, KGChunkIndex, LINK_PREDICATE

PREFIX = "http://dbpedia.org/resource/"


def edge(source, target, predicate=LINK_PREDICATE):
    return {"source": PREFIX + source, "target": PREFIX + target, "predicate": predicate}


def index(chunks, edges, mode="graph", config=None):
    names = {uri.removeprefix(PREFIX) for e in edges for uri in (e["source"], e["target"])}
    nodes = [{"uri": PREFIX + name, "label": name, "aliases": []} for name in sorted(names)]
    return KGChunkIndex(EntityMatcher(nodes), chunks, edges=edges, mode=mode, config=config)


class GraphTraversalTests(unittest.TestCase):
    def test_recovers_neighbor_evidence_without_a_direct_mention(self):
        chunks = ["Beta evidence", "unrelated evidence", "other evidence"]
        edges = [edge("Alpha", "Beta")]
        mentions = index(chunks, edges, mode="mentions")
        graph = index(chunks, edges)
        self.assertEqual(mentions.rank("Alpha"), [])
        self.assertEqual(graph.rank("Alpha"), [0])
        result = graph.retrieve("Alpha")
        self.assertEqual(result["hits"][0]["direct_entities"], [])
        self.assertEqual(result["hits"][0]["expanded_entities"], [PREFIX + "Beta"])
        via = result["expansions"][0]["via"][0]
        self.assertEqual(via["seed"], PREFIX + "Alpha")
        self.assertEqual(via["predicate"], LINK_PREDICATE)
        self.assertEqual(via["directions"], ["outgoing"])

    def test_one_hop_does_not_follow_neighbors_of_neighbors(self):
        graph = index(["Beta", "Gamma", "other"], [edge("Alpha", "Beta"), edge("Beta", "Gamma")])
        self.assertEqual(graph.rank("Alpha"), [0])

    def test_incoming_and_outgoing_have_explicit_direction(self):
        chunks, edges = ["Beta", "other"], [edge("Beta", "Alpha")]
        self.assertEqual(index(chunks, edges, config=GraphConfig(direction="outgoing")).rank("Alpha"), [])
        result = index(chunks, edges, config=GraphConfig(direction="incoming")).retrieve("Alpha")
        self.assertEqual([h["chunk_id"] for h in result["hits"]], [0])
        self.assertEqual(result["expansions"][0]["via"][0]["directions"], ["incoming"])

    def test_duplicate_reciprocal_edges_and_self_loops_do_not_inflate_scores(self):
        chunks = ["Alpha", "Beta", "other"]
        single = index(chunks, [edge("Alpha", "Beta")]).retrieve("Alpha")
        repeated = index(chunks, [edge("Alpha", "Beta"), edge("Alpha", "Beta"), edge("Beta", "Alpha"), edge("Alpha", "Alpha")]).retrieve("Alpha")
        self.assertEqual(single["hits"], repeated["hits"])
        self.assertEqual(repeated["expansions"][0]["via"][0]["directions"], ["incoming", "outgoing"])

    def test_disallowed_predicate_does_not_expand(self):
        graph = index(["Beta", "other"], [edge("Alpha", "Beta", "http://example.org/causes")])
        self.assertEqual(graph.rank("Alpha"), [])

    def test_high_degree_and_frequent_neighbors_are_filtered(self):
        edges = [edge("Alpha", "Hub"), edge("Hub", "Beta"), edge("Hub", "Gamma"), edge("Alpha", "Common")]
        graph = index(["Hub Common", "Common", "Common", "other"], edges,
                      config=GraphConfig(max_neighbor_degree=2, max_neighbor_document_ratio=0.5))
        self.assertEqual(graph.rank("Alpha"), [])

    def test_only_neighbors_present_in_the_corpus_are_candidates(self):
        graph = index(["Beta", "other"], [edge("Alpha", "Beta"), edge("Alpha", "Absent")])
        result = graph.retrieve("Alpha")
        self.assertEqual([e["entity"] for e in result["expansions"]], [PREFIX + "Beta"])

    def test_direct_mentions_keep_full_weight_and_are_not_expanded_again(self):
        graph = index(["Alpha Beta", "other", "other"], [edge("Alpha", "Beta")])
        result = graph.retrieve("Alpha Beta")
        self.assertEqual(result["expansions"], [])
        self.assertAlmostEqual(result["hits"][0]["score"], 2 * (1 + math.log(4 / 2)))

    def test_shared_neighbor_retains_paths_from_both_seeds(self):
        graph = index(["Bridge", "other", "other"], [edge("Alpha", "Bridge"), edge("Gamma", "Bridge")])
        result = graph.retrieve("Alpha Gamma")
        expansion = result["expansions"][0]
        self.assertEqual({p["seed"] for p in expansion["via"]}, {PREFIX + "Alpha", PREFIX + "Gamma"})
        self.assertAlmostEqual(expansion["weight"], 0.25 * 2 * (1 + math.log(4)))

    def test_expansion_mass_is_bounded_per_seed(self):
        edges = [edge("Alpha", "Beta"), edge("Alpha", "Gamma"), edge("Alpha", "Delta")]
        graph = index(["Alpha", "Beta Gamma Delta", "other", "other"], edges)
        result = graph.retrieve("Alpha")
        direct_score = next(h["score"] for h in result["hits"] if h["chunk_id"] == 0)
        expanded_score = next(h["score"] for h in result["hits"] if h["chunk_id"] == 1)
        self.assertAlmostEqual(expanded_score, 0.25 * direct_score)
        self.assertEqual(graph.rank("Alpha")[0], 0)

    def test_degree_penalty_favors_specific_neighbors(self):
        edges = [edge("Alpha", "Beta"), edge("Alpha", "Hub"), edge("Hub", "Gamma"), edge("Hub", "Delta")]
        result = index(["Beta", "Hub", "other", "other"], edges).retrieve("Alpha")
        weights = {e["entity"]: e["weight"] for e in result["expansions"]}
        self.assertGreater(weights[PREFIX + "Beta"], weights[PREFIX + "Hub"])

    def test_limits_and_ties_are_deterministic(self):
        edges = [edge(seed, neighbor) for seed in ("Alpha", "Beta", "Gamma") for neighbor in ("Delta", "Epsilon", "Zeta")]
        config = GraphConfig(max_seeds=2, max_neighbors=2, max_expanded_entities=1)
        chunks = ["Delta", "Epsilon", "Zeta", "other"]
        result = index(chunks, edges, config=config).retrieve("Gamma Beta Alpha")
        shuffled = index(chunks, list(reversed(edges)), config=config).retrieve("Alpha Beta Gamma")
        self.assertEqual(result, shuffled)
        self.assertEqual(len(result["expansion_seeds"]), 2)
        self.assertEqual(len(result["expansions"]), 1)
        self.assertEqual(len(result["expansions"][0]["via"]), 2)

    def test_zero_limits_or_weight_preserve_mentions_ranking(self):
        chunks, edges = ["Alpha", "Beta", "other"], [edge("Alpha", "Beta")]
        expected = index(chunks, edges, mode="mentions").rank("Alpha")
        for field in ("max_seeds", "max_neighbors", "max_expanded_entities", "max_neighbor_degree", "expansion_weight", "max_neighbor_document_ratio"):
            with self.subTest(field=field):
                config = replace(GraphConfig(), **{field: 0})
                self.assertEqual(index(chunks, edges, config=config).rank("Alpha"), expected)

    def test_empty_corpus_unknown_question_and_zero_top_k(self):
        edges = [edge("Alpha", "Beta")]
        self.assertEqual(index([], edges).rank("Alpha"), [])
        graph = index(["Beta", "other"], edges)
        self.assertEqual(graph.rank("unmatched"), [])
        self.assertEqual(graph.rank("Alpha", top_k=0), [])


class GraphConfigTests(unittest.TestCase):
    def test_rejects_invalid_limits_weights_and_directions(self):
        for kwargs in ({"max_seeds": -1}, {"max_neighbors": 1.5}, {"expansion_weight": float("nan")},
                       {"expansion_weight": 2}, {"max_neighbor_document_ratio": -0.1}, {"direction": "random"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                GraphConfig(**kwargs)

    def test_environment_configuration_is_explicit_and_hashable(self):
        with patch.dict(os.environ, {"KG_GRAPH_MAX_NEIGHBORS": "3", "KG_GRAPH_EXPANSION_WEIGHT": "0.1"}, clear=True):
            config = GraphConfig.from_env()
        self.assertEqual(config.max_neighbors, 3)
        self.assertEqual(config.expansion_weight, 0.1)
        self.assertEqual({config: "cached"}[config], "cached")
        with patch.dict(os.environ, {"KG_GRAPH_MAX_NEIGHBORS": "bad"}, clear=True), self.assertRaises(ValueError):
            GraphConfig.from_env()


if __name__ == "__main__":
    unittest.main()
