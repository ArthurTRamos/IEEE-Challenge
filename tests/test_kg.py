"""Entity postings, artifact validation and offline conversion tests."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.kg_retrieval import FILES, EntityMatcher, KGChunkIndex, load_artifact
from tools.prepare_kg import prepare

DBR = "http://dbpedia.org/resource/"


def node(name, aliases=()):
    return {"uri": DBR + name.replace(" ", "_"), "label": name, "aliases": list(aliases)}


def write_artifact(directory, nodes, edges=()):
    for name, records in (("nodes.jsonl", nodes), ("edges.jsonl", edges)):
        (directory / name).write_text("".join(json.dumps(row) + "\n" for row in records))
    (directory / "audit.json").write_text('{}\n')
    manifest = {
        "schema_version": 1, "retrieval": "entity-mentions-v1",
        "counts": {"nodes": len(nodes), "edges": len(edges)},
        "files": {name: {"bytes": (directory / name).stat().st_size,
                         "sha256": hashlib.sha256((directory / name).read_bytes()).hexdigest()} for name in FILES},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))


class EntityMatcherTests(unittest.TestCase):
    def test_aliases_link_different_names_to_same_entity(self):
        be7 = node("Beryllium-7", ["Be7", "Be-7", "7Be"])
        matcher = EntityMatcher([be7])
        for name in ["Beryllium-7", "BE7", "Be-7", "7Be", "(Be7)"]:
            with self.subTest(name=name):
                self.assertEqual(matcher.match(f"Decay of {name}?"), {be7["uri"]})

    def test_unicode_casefold_and_hyphen_boundaries(self):
        concept = node("Neutrón source")
        self.assertEqual(EntityMatcher([concept]).match("NEUTRÓN-source!"), {concept["uri"]})

    def test_longest_phrase_avoids_linking_nested_concepts(self):
        lithium, compound = node("Lithium"), node("Lithium carbonate")
        matcher = EntityMatcher([lithium, compound])
        self.assertEqual(matcher.match("lithium carbonate"), {compound["uri"]})
        self.assertEqual(matcher.match("lithium and lithium carbonate"), {lithium["uri"], compound["uri"]})

    def test_matches_words_not_substrings(self):
        matcher = EntityMatcher([node("Lithium", ["Li"]), node("Linear")])
        self.assertEqual(matcher.match("nonlinear lithiums Li"), set())

    def test_ambiguous_aliases_are_not_arbitrarily_resolved(self):
        first, second = node("First concept", ["Shared alias"]), node("Second concept", ["Shared alias"])
        matcher = EntityMatcher([first, second])
        self.assertEqual(matcher.match("Shared alias"), set())
        self.assertEqual(matcher.match("First concept"), {first["uri"]})
        self.assertEqual(matcher.ambiguous_count, 1)

    def test_unique_canonical_label_takes_precedence_over_general_page_alias(self):
        isotope = node("Beryllium-7", ["Be7"])
        group = node("Isotopes of beryllium", ["Beryllium-7"])
        matcher = EntityMatcher([isotope, group])
        self.assertEqual(matcher.match("Beryllium-7"), {isotope["uri"]})
        self.assertEqual(matcher.match("Be7"), {isotope["uri"]})
        self.assertEqual(matcher.canonical_resolution_count, 1)

    def test_shared_canonical_labels_still_require_disambiguation(self):
        first, second = node("Shared name"), node("Other name")
        second["label"] = "Shared name"
        self.assertEqual(EntityMatcher([first, second]).match("Shared name"), set())

    def test_repeated_mentions_are_deduplicated(self):
        concept = node("Lithium")
        self.assertEqual(EntityMatcher([concept]).match("Lithium lithium LITHIUM"), {concept["uri"]})

    def test_math_symbols_are_not_stripped_into_generic_aliases(self):
        concept = node("GNS construction", ["*-representation"])
        matcher = EntityMatcher([concept])
        self.assertEqual(matcher.match("representation generator"), set())
        self.assertEqual(matcher.match("*-representation"), {concept["uri"]})

    def test_qualified_names_do_not_match_ordinary_nouns(self):
        matcher = EntityMatcher([node("Building (mathematics)")])
        self.assertEqual(matcher.match("main building in the facility"), set())


class KGPostingsTests(unittest.TestCase):
    def setUp(self):
        self.alpha, self.beta = node("Alpha concept", ["alpha"]), node("Beta concept", ["beta"])
        matcher = EntityMatcher([self.alpha, self.beta])
        self.index = KGChunkIndex(matcher, ["alpha alpha alpha", "alpha and beta", "beta", "other evidence"])

    def test_postings_preserve_chunk_ids(self):
        self.assertEqual(self.index.postings[self.alpha["uri"]], [0, 1])
        self.assertEqual(self.index.postings[self.beta["uri"]], [1, 2])

    def test_chunks_covering_both_question_entities_rank_first(self):
        self.assertEqual(self.index.rank("alpha beta"), [1, 0, 2])
        self.assertEqual(self.index.rank("alpha beta", top_k=1), [1])

    def test_no_entity_or_no_corpus_mention_returns_no_candidates(self):
        self.assertEqual(self.index.rank("unmatched"), [])
        self.assertEqual(KGChunkIndex(self.index.matcher, []).rank("alpha"), [])
        self.assertEqual(self.index.rank("alpha", top_k=0), [])

    def test_rare_entities_receive_more_weight(self):
        index = KGChunkIndex(self.index.matcher, ["alpha", "alpha", "beta"])
        self.assertEqual(index.rank("alpha beta"), [2, 0, 1])


class KGArtifactTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)

    def test_loads_valid_artifact_and_builds_postings(self):
        concept = node("Lithium")
        write_artifact(self.path, [concept])
        manifest, nodes, edges = load_artifact(self.path)
        self.assertEqual(manifest["counts"], {"nodes": 1, "edges": 0})
        self.assertEqual(nodes, [concept])
        self.assertEqual(edges, [])
        self.assertEqual(KGChunkIndex.from_directory(self.path, ["Lithium target"]).rank("lithium"), [0])

    def test_corrupt_file_fails_instead_of_silent_fallback(self):
        write_artifact(self.path, [node("Lithium")])
        with (self.path / "nodes.jsonl").open("a") as handle:
            handle.write(" ")
        with self.assertRaisesRegex(ValueError, "checksum"):
            load_artifact(self.path)

    def test_unknown_schema_is_rejected(self):
        write_artifact(self.path, [node("Lithium")])
        path = self.path / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["schema_version"] = 99
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "schema"):
            load_artifact(self.path)

    def test_duplicate_entities_are_rejected(self):
        write_artifact(self.path, [node("Lithium"), node("Lithium")])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_artifact(self.path)

    def test_edges_cannot_reference_absent_entities(self):
        edge = {"source": DBR + "Lithium", "predicate": "http://dbpedia.org/ontology/wikiPageWikiLink", "target": DBR + "Absent"}
        write_artifact(self.path, [node("Lithium")], [edge])
        with self.assertRaisesRegex(ValueError, "unknown entity"):
            load_artifact(self.path)

    def test_only_known_association_predicate_is_accepted(self):
        edge = {"source": DBR + "Lithium", "predicate": "http://example.org/causes", "target": DBR + "Lithium"}
        write_artifact(self.path, [node("Lithium")], [edge])
        with self.assertRaisesRegex(ValueError, "relation"):
            load_artifact(self.path)

    def test_converter_preserves_original_data_and_rdf_property_metadata(self):
        inputs = self.path / "input"
        inputs.mkdir()
        record = {**node("Beryllium-7"), "definition": "", "properties": [], "categories": [], "related_concepts": []}
        cards = inputs / "kg_rag_chunks.jsonl"
        cards.write_text(json.dumps(record) + "\n")
        ttl = inputs / "domain_kg.ttl"
        ttl.write_text('''@prefix dbr: <http://dbpedia.org/resource/> .
@prefix dbo: <http://dbpedia.org/ontology/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
dbr:Beryllium-7 rdfs:label "Beryllium-7"@en ; dbo:halfLife "53.22"^^xsd:decimal .
''')
        original = (cards.read_bytes(), ttl.read_bytes())
        alias_path = self.path / "aliases.json"
        alias_path.write_text(json.dumps({record["uri"]: ["Be7"]}))
        output = self.path / "output"
        _, audit = prepare(inputs, output, alias_path)
        manifest, nodes, _ = load_artifact(output)
        self.assertEqual((cards.read_bytes(), ttl.read_bytes()), original)
        self.assertEqual(manifest["source"]["extraction_date"], None)
        self.assertEqual(nodes[0]["properties"][0]["datatype"], "http://www.w3.org/2001/XMLSchema#decimal")
        self.assertEqual(nodes[0]["properties"][0]["value"], "53.22")
        self.assertEqual(audit["entities_with_definition"], 0)
        self.assertIn("Be7", nodes[0]["aliases"])
        self.assertEqual(KGChunkIndex.from_directory(output, ["Beryllium-7 decays"]).rank("Be7"), [0])


if __name__ == "__main__":
    unittest.main()
