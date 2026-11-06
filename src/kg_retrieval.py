"""Offline entity linking and chunk retrieval; standard library only.

DBpedia identifies concepts and supplies bounded one-hop associations. All
evidence returned to the LLM still comes from corpus chunks.
"""

import hashlib
import json
import math
import os
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, fields
from pathlib import Path

SCHEMA_VERSION = 1
MAX_KG_BYTES = 100_000_000
FILES = ("nodes.jsonl", "edges.jsonl", "audit.json")
LINK_PREDICATE = "http://dbpedia.org/ontology/wikiPageWikiLink"
_END = ""
_COMMON_WORDS = frozenset("the and for with from that this are was not can all has its how why what".split())


def tokens(text):
    """Case-insensitive Unicode words, treating hyphens as word boundaries."""
    # Keep mathematical operators: '*-representation' must not become the
    # generic word 'representation', and 'C++' must not become 'C'.
    return re.findall(r"[^\W_]+|[+*/^=<>|]", unicodedata.normalize("NFKC", text).casefold())


def load_artifact(directory):
    directory = Path(directory)
    names = ("manifest.json", *FILES)
    if sum((directory / name).stat().st_size for name in names) > MAX_KG_BYTES:
        raise ValueError("KG exceeds its 100 MB uncompressed budget")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported KG schema version")
    if manifest.get("retrieval") != "entity-mentions-v1" or set(manifest.get("files", {})) != set(FILES):
        raise ValueError("Unsupported KG representation or file list")
    for name in FILES:
        data = (directory / name).read_bytes()
        expected = manifest["files"][name]
        if len(data) != expected.get("bytes") or hashlib.sha256(data).hexdigest() != expected.get("sha256"):
            raise ValueError(f"KG checksum/size mismatch: {name}")
    nodes = [json.loads(line) for line in (directory / "nodes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    by_uri = {}
    for node in nodes:
        uri = node.get("uri")
        if not isinstance(uri, str) or not uri.startswith("http://dbpedia.org/resource/") or uri in by_uri:
            raise ValueError(f"Invalid or duplicate KG URI: {uri}")
        if not isinstance(node.get("label"), str) or not node["label"].strip():
            raise ValueError(f"Missing KG label: {uri}")
        aliases = node.get("aliases")
        if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
            raise ValueError(f"Invalid KG aliases: {uri}")
        by_uri[uri] = node
    if not nodes or manifest.get("counts", {}).get("nodes") != len(nodes):
        raise ValueError("KG node count mismatch or empty graph")
    edges = []
    with (directory / "edges.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            edge = json.loads(line)
            if edge.get("source") not in by_uri or edge.get("target") not in by_uri:
                raise ValueError("KG edge references an unknown entity")
            if edge.get("predicate") != LINK_PREDICATE:
                raise ValueError("Unsupported KG edge relation")
            edges.append(edge)
    if manifest.get("counts", {}).get("edges") != len(edges):
        raise ValueError("KG edge count mismatch")
    return manifest, nodes, edges


class EntityMatcher:
    """Token trie: longest phrase wins; a unique canonical label beats aliases.

    Remaining ambiguous phrases are not linked.

    Prefix matching is intentionally avoided: 'Li' must not match 'linear'.
    Very short and common names are excluded. No LLM or encoder is used.
    """

    def __init__(self, nodes):
        self.trie = {}
        self.alias_count = 0
        aliases = defaultdict(set)
        canonical = defaultdict(set)
        for node in nodes:
            canonical[tuple(tokens(node["label"]))].add(node["uri"])
            for name in [node["label"], *node["aliases"]]:
                phrase = tuple(tokens(name))
                if not phrase or len(phrase) > 12:
                    continue
                if len(phrase) == 1 and (len(phrase[0]) < 3 or phrase[0] in _COMMON_WORDS):
                    continue
                aliases[phrase].add(node["uri"])
        self.canonical_resolution_count = 0
        for phrase in aliases:
            if phrase in canonical:
                if len(aliases[phrase]) > 1 and len(canonical[phrase]) == 1:
                    self.canonical_resolution_count += 1
                aliases[phrase] = canonical[phrase]
        self.ambiguous_count = sum(len(uris) > 1 for uris in aliases.values())
        for phrase, uris in sorted(aliases.items()):
            branch = self.trie
            for token in phrase:
                branch = branch.setdefault(token, {})
            branch[_END] = frozenset(uris)
        self.alias_count = len(aliases)

    def match(self, text):
        words = tokens(text)
        found = set()
        start = 0
        while start < len(words):
            branch = self.trie
            best = None
            end = start
            while end < len(words) and words[end] in branch:
                branch = branch[words[end]]
                end += 1
                if _END in branch:
                    best = (end, branch[_END])
            if best is None:
                start += 1
                continue
            start, uris = best
            if len(uris) == 1:
                found.update(uris)
        return found


@dataclass(frozen=True)
class GraphConfig:
    """Experimental expansion limits; no extra model or GPU allocation."""

    expansion_weight: float = 0.25
    max_seeds: int = 8
    max_neighbors: int = 8
    max_expanded_entities: int = 32
    max_neighbor_degree: int = 256
    max_neighbor_document_ratio: float = 0.5
    direction: str = "both"

    def __post_init__(self):
        for name in ("max_seeds", "max_neighbors", "max_expanded_entities", "max_neighbor_degree"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        for name in ("expansion_weight", "max_neighbor_document_ratio"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and between 0 and 1")
        if self.direction not in ("both", "incoming", "outgoing"):
            raise ValueError("direction must be both, incoming or outgoing")

    @classmethod
    def from_env(cls):
        defaults = cls()
        values = {}
        for field in fields(cls):
            name = field.name
            raw = os.environ.get(f"KG_GRAPH_{name.upper()}")
            if raw is not None:
                try:
                    values[name] = type(getattr(defaults, name))(raw)
                except ValueError as exc:
                    raise ValueError(f"Invalid KG_GRAPH_{name.upper()}: {raw}") from exc
        return cls(**values)


class KGChunkIndex:
    """Entity postings plus optional, traceable one-hop graph expansion."""

    def __init__(self, matcher, chunks, *, edges=(), mode="mentions", config=None):
        if mode not in ("mentions", "graph"):
            raise ValueError("KG index mode must be mentions or graph")
        self.matcher = matcher
        self.chunk_count = len(chunks)
        self.mode = mode
        self.config = config or GraphConfig()
        self.chunk_entities = []
        postings = defaultdict(list)
        for chunk_id, chunk in enumerate(chunks):
            entities = frozenset(matcher.match(chunk))
            self.chunk_entities.append(entities)
            for uri in sorted(entities):
                postings[uri].append(chunk_id)
        self.postings = dict(postings)
        self.neighbors = {}
        self.degrees = {}
        if mode == "graph":
            self._prepare_neighbors(edges)

    @classmethod
    def from_directory(cls, directory, chunks, *, mode="mentions", config=None):
        _, nodes, edges = load_artifact(directory)
        return cls(EntityMatcher(nodes), chunks, edges=edges, mode=mode, config=config)

    def _idf(self, uri):
        return 1.0 + math.log((1 + self.chunk_count) / (1 + len(self.postings.get(uri, ()))))

    def _prepare_neighbors(self, edges):
        # Keep original direction in the trace. Both-direction traversal is
        # allowed for associations; it does not assert that links are causal.
        adjacency = defaultdict(lambda: defaultdict(set))
        for edge in edges:
            if edge["predicate"] != LINK_PREDICATE or edge["source"] == edge["target"]:
                continue
            source, target = edge["source"], edge["target"]
            adjacency[source][target].add("outgoing")
            adjacency[target][source].add("incoming")
        self.degrees = {uri: len(neighbors) for uri, neighbors in adjacency.items()}
        config = self.config
        if not self.chunk_count or not config.max_neighbors:
            return
        for seed, neighbors in adjacency.items():
            eligible = []
            for uri, directions in neighbors.items():
                if config.direction != "both":
                    directions = directions & {config.direction}
                degree = self.degrees[uri]
                frequency = len(self.postings.get(uri, ()))
                if not directions or not frequency or degree > config.max_neighbor_degree:
                    continue
                if frequency / self.chunk_count > config.max_neighbor_document_ratio:
                    continue
                preference = self._idf(uri) / math.sqrt(1 + degree)
                eligible.append({"uri": uri, "preference": preference, "degree": degree,
                                 "directions": sorted(directions)})
            # Build these bounded lists once; query-time traversal never scans
            # the whole graph, including for very high-degree query seeds.
            eligible.sort(key=lambda item: (-item["preference"], item["uri"]))
            if eligible:
                self.neighbors[seed] = tuple(eligible[:config.max_neighbors])

    def _expand(self, matched):
        config = self.config
        if self.mode != "graph" or not config.expansion_weight or not config.max_expanded_entities:
            return [], []
        seeds = sorted(matched, key=lambda uri: (-self._idf(uri), uri))[:config.max_seeds]
        candidates = defaultdict(dict)
        for seed in seeds:
            for neighbor in self.neighbors.get(seed, ()):
                if neighbor["uri"] not in matched:
                    candidates[neighbor["uri"]][seed] = neighbor
        priorities = {uri: sum(self._idf(seed) * item["preference"] for seed, item in paths.items())
                      for uri, paths in candidates.items()}
        selected = sorted(candidates, key=lambda uri: (-priorities[uri], uri))[:config.max_expanded_entities]
        normalizers = defaultdict(float)
        for uri in selected:
            for seed, item in candidates[uri].items():
                normalizers[seed] += item["preference"]
        expansions = []
        for uri in selected:
            via = []
            for seed, item in sorted(candidates[uri].items()):
                contribution = (config.expansion_weight * self._idf(seed)
                                * item["preference"] / normalizers[seed])
                via.append({"seed": seed, "predicate": LINK_PREDICATE,
                            "directions": item["directions"], "contribution": contribution})
            expansions.append({"entity": uri, "weight": sum(path["contribution"] for path in via),
                               "degree": self.degrees[uri], "via": via})
        return seeds, expansions

    def retrieve(self, question, top_k=100):
        """Return scored corpus hits and the entity/edge paths that explain them."""
        if top_k <= 0:
            return {"mode": self.mode, "matched_entities": [], "expansion_seeds": [], "expansions": [], "hits": []}
        matched = self.matcher.match(question)
        seeds, expansions = self._expand(matched)
        direct_weights = {uri: self._idf(uri) for uri in sorted(matched) if uri in self.postings}
        expanded_weights = {item["entity"]: item["weight"] for item in expansions}
        scores = defaultdict(float)
        for uri, weight in [*direct_weights.items(), *expanded_weights.items()]:
            for chunk_id in self.postings[uri]:
                scores[chunk_id] += weight
        order = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:top_k]
        hits = [{"chunk_id": chunk_id, "score": scores[chunk_id],
                 "direct_entities": sorted(self.chunk_entities[chunk_id] & direct_weights.keys()),
                 "expanded_entities": sorted(self.chunk_entities[chunk_id] & expanded_weights.keys())}
                for chunk_id in order]
        return {"mode": self.mode, "matched_entities": sorted(matched), "expansion_seeds": seeds,
                "expansions": expansions, "hits": hits}

    def rank(self, question, top_k=100):
        return [hit["chunk_id"] for hit in self.retrieve(question, top_k)["hits"]]
