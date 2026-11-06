#!/usr/bin/env python3
"""Audit notebook exports and prepare the offline artifact used by main.py.

Run from the repository: python tools/prepare_kg.py. RDFLib is used only here.
The original data/ files are never rewritten.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kg_retrieval import FILES, MAX_KG_BYTES, SCHEMA_VERSION, EntityMatcher, load_artifact, tokens

LINK = "http://dbpedia.org/ontology/wikiPageWikiLink"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def prepare(input_dir, output_dir, aliases_path):
    import rdflib
    from rdflib.namespace import DCTERMS, RDFS, SKOS

    input_dir, output_dir = Path(input_dir), Path(output_dir)
    cards_path = input_dir / "kg_rag_chunks.jsonl"
    ttl_path = input_dir / "domain_kg.ttl"
    records = [json.loads(line) for line in cards_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records or len({r["uri"] for r in records}) != len(records):
        raise ValueError("Input node cards are empty or contain duplicate URIs")
    graph = rdflib.Graph().parse(ttl_path, format="turtle")
    curated = json.loads(Path(aliases_path).read_text(encoding="utf-8"))
    nodes = []
    for record in sorted(records, key=lambda r: r["uri"]):
        uri, label = record["uri"], record["label"]
        subject = rdflib.URIRef(uri)
        labels = {str(value) for value in graph.objects(subject, RDFS.label)}
        if label not in labels:
            raise ValueError(f"Card label missing from Turtle: {uri}")
        alias_sources = defaultdict(set)
        for alias in record["aliases"]:
            alias_sources[alias].add("notebook_redirect")
        for alias in curated.get(uri, []):
            alias_sources[alias].add("tools/kg_aliases.json")
        properties = []
        for predicate, value in graph.predicate_objects(subject):
            if predicate in (RDFS.label, RDFS.comment, DCTERMS.subject, SKOS.broader) or str(predicate) == LINK:
                continue
            prop = {"predicate": str(predicate), "value": str(value), "type": "uri" if isinstance(value, rdflib.URIRef) else "literal"}
            if isinstance(value, rdflib.Literal):
                if value.datatype:
                    prop["datatype"] = str(value.datatype)
                if value.language:
                    prop["language"] = value.language
            properties.append(prop)
        # These describe the available input, not data absent from the notebook.
        nodes.append({
            "uri": uri, "label": label,
            "aliases": sorted(alias_sources),
            "alias_sources": {alias: sorted(sources) for alias, sources in sorted(alias_sources.items())},
            "definition": record["definition"],
            "categories": sorted(set(record["categories"])),
            "properties": sorted(properties, key=lambda p: (p["predicate"], p["value"])),
        })
    by_uri = {node["uri"]: node for node in nodes}
    missing_curated = sorted(set(curated) - set(by_uri))
    if missing_curated:
        raise ValueError(f"Curated alias refers to absent entities: {missing_curated}")
    edges = []
    excluded_links = 0
    for source, target in graph.subject_objects(rdflib.URIRef(LINK)):
        if str(source) in by_uri and str(target) in by_uri:
            edges.append({"source": str(source), "predicate": LINK, "target": str(target)})
        else:
            excluded_links += 1
    edges.sort(key=lambda e: (e["source"], e["target"]))
    matcher = EntityMatcher(nodes)
    aliases = defaultdict(set)
    for node in nodes:
        for alias in [node["label"], *node["aliases"]]:
            aliases[tuple(tokens(alias))].add(node["uri"])
    degree = Counter()
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    warnings = [
        "Original extraction timestamp, endpoint revision and query completeness are unknown.",
        "The notebook discarded literal datatype/language before Turtle export; they cannot be reconstructed here.",
        "wikiPageWikiLink is an editorial association, not a causal or equivalence relation.",
    ]
    if not any(n["definition"] for n in nodes):
        warnings.append("All definitions are empty. This artifact supports mention retrieval, not definitional context.")
    audit = {
        "input_cards": len(records), "rdf_triples": len(graph),
        "entities_with_definition": sum(bool(n["definition"]) for n in nodes),
        "entities_with_properties": sum(bool(n["properties"]) for n in nodes),
        "entities_with_exported_aliases": sum(bool(r["aliases"]) for r in records),
        "exported_aliases": sum(len(r["aliases"]) for r in records),
        "searchable_aliases": matcher.alias_count, "ambiguous_searchable_aliases": matcher.ambiguous_count,
        "collisions_resolved_by_canonical_label": matcher.canonical_resolution_count,
        "internal_links": len(edges), "links_to_absent_entities": excluded_links,
        "predicates": dict(sorted(Counter(str(p) for _, p, _ in graph).items())),
        "top_degree_entities": [{"uri": uri, "label": by_uri[uri]["label"], "degree": count} for uri, count in degree.most_common(10)],
        "raw_alias_collision_examples": [{"alias": " ".join(alias), "uris": sorted(uris)} for alias, uris in sorted(aliases.items()) if len(uris) > 1][:20],
        "warnings": warnings,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").unlink(missing_ok=True)
    for name, rows in (("nodes.jsonl", nodes), ("edges.jsonl", edges)):
        with (output_dir / name).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    write_json(output_dir / "audit.json", audit)
    manifest = {
        "schema_version": SCHEMA_VERSION, "retrieval": "entity-mentions-v1",
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"name": "DBpedia", "endpoint": "https://dbpedia.org/sparql", "extraction_date": None,
                   "attribution_url": "https://www.dbpedia.org/", "license_reference": "https://www.dbpedia.org/about/",
                   "notebook": "notebooks/dbpedia/01_extract_domain_kg.ipynb"},
        "inputs": {name: sha256(input_dir / name) for name in ("domain_kg.ttl", "kg_rag_chunks.jsonl")},
        "curated_aliases_sha256": sha256(aliases_path),
        "files": {name: {"bytes": (output_dir / name).stat().st_size, "sha256": sha256(output_dir / name)} for name in FILES},
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }
    write_json(output_dir / "manifest.json", manifest)
    size = sum((output_dir / name).stat().st_size for name in ("manifest.json", *FILES))
    if size > MAX_KG_BYTES:
        (output_dir / "manifest.json").unlink()
        raise ValueError(f"Artifact exceeds {MAX_KG_BYTES:,} bytes: {size:,}")
    load_artifact(output_dir)
    print(json.dumps({"artifact": str(output_dir), "bytes": size, **manifest["counts"],
                      "definitions": audit["entities_with_definition"], "entities_with_properties": audit["entities_with_properties"]}, indent=2))
    return manifest, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "src/kg")
    parser.add_argument("--aliases", type=Path, default=ROOT / "tools/kg_aliases.json")
    args = parser.parse_args()
    prepare(args.input_dir, args.output_dir, args.aliases)


if __name__ == "__main__":
    main()
