"""Section-aware chunking, lightweight evidence penalties and bounded continuity."""

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EvidenceConfig:
    reference_weight: float = 0.5
    front_matter_weight: float = 0.7
    neighbors_before: int = 1
    neighbors_after: int = 3
    small_section_chunks: int = 6
    max_chunks: int = 10

    def __post_init__(self):
        for value in (self.reference_weight, self.front_matter_weight):
            if not 0 < value <= 1:
                raise ValueError("Evidence penalty weights must be in (0, 1]")
        for value in (self.neighbors_before, self.neighbors_after, self.small_section_chunks):
            if type(value) is not int or value < 0:
                raise ValueError("Continuity limits must be nonnegative integers")
        if type(self.max_chunks) is not int or self.max_chunks <= 0:
            raise ValueError("max_chunks must be positive")

    def to_dict(self):
        return asdict(self)


def _paragraphs(text):
    # Blank lines inside display math and fenced code do not split an atom.
    lines, math_end, fence = [], None, None
    for line in text.splitlines():
        stripped = line.strip()
        if not math_end and (stripped.startswith('```') or stripped.startswith('~~~')):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
        if not fence:
            if math_end:
                if math_end in stripped:
                    math_end = None
            elif stripped.startswith('$$') and stripped.count('$$') == 1:
                math_end = '$$'
            elif stripped.startswith(r'\[') and r'\]' not in stripped:
                math_end = r'\]'
            elif re.match(r'\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}', stripped):
                environment = re.match(r'\\begin\{([^}]+)\}', stripped).group(1)
                if rf'\end{{{environment}}}' not in stripped:
                    math_end = rf'\end{{{environment}}}'
        if not stripped and not math_end and not fence:
            if lines:
                yield '\n'.join(lines).strip()
                lines = []
        else:
            lines.append(line)
    if lines:
        yield '\n'.join(lines).strip()


def section_chunks(text, chunk_size=800, overlap=150):
    """Never carry overlap across headings or split a display-math paragraph.

    A heading starts a chunk, so inherited section labels remain unambiguous.
    Oversized indivisible paragraphs/formulas are retained instead of corrupted.
    """
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError("Invalid chunk size/overlap")
    chunks, current = [], ''
    for paragraph in _paragraphs(text):
        # Docling headings are normally separate paragraphs. Split a leading
        # heading from the body as well, including Markdown without blank lines.
        parts = re.split(r'(?m)(?=^#{1,6}\s+)', paragraph) if not paragraph.startswith(('```', '~~~', '$$', r'\[', r'\begin')) else [paragraph]
        for part in parts:
            part = part.strip()
            if not part:
                continue
            heading = re.match(r'^#{1,6}\s+', part) is not None
            heading_only = bool(re.fullmatch(r'#{1,6}\s+[^\n]+', current))
            if current and (heading or (not heading_only and len(current) + len(part) + 2 > chunk_size)):
                chunks.append(current)
                last = current.rsplit('\n\n', 1)[-1]
                structured = any(marker in last for marker in ('$$', r'\[', r'\]', r'\begin', r'\end', '```', '~~~'))
                tail = '' if structured else re.sub(r'(?m)^#{1,6}\s+.*$', '', last)[-overlap:]
                current = '' if heading or not overlap else tail
            current = f'{current}\n\n{part}' if current else part
    if current:
        chunks.append(current)
    return chunks


def _heading_name(text):
    return re.sub(r'^[\dIVXivx.\s)\-]+', '', text).strip().casefold()


def content_kind(text, section, local_index):
    heading = _heading_name(section or '')
    if re.fullmatch(r'(references|bibliography|bibliografia|referências|literature cited)', heading):
        return 'references'
    # Conservative front matter detection: do not treat substantive abstracts
    # or an entire first page as a cover just because it is first in the PDF.
    words = re.findall(r'\w+', text)
    if local_index <= 2 and len(words) <= 100:
        body = re.sub(r'(?m)^#{1,6}\s+.*$', '', text).strip()
        substantive = re.search(r'(?im)^\s*(?:#{1,6}\s*)?(abstract|introduction|proof|theorem)\b', text)
        affiliations = re.search(r'@|\b(university|universit[àé]|department|institute|school of|corresponding author)\b', body, re.I)
        if not substantive and (not body or (affiliations and len(words) <= 80)):
            return 'front_matter'
    return 'body'


def chunk_sources(document, chunks):
    sources, hierarchy = [], []
    section, section_id = None, -1
    for local_id, chunk in enumerate(chunks):
        headings = re.findall(r'(?m)^(#{1,6})\s+(.+)$', chunk)
        if headings:
            section_id += 1
            for hashes, title in headings:
                level = len(hashes)
                hierarchy = [(depth, label) for depth, label in hierarchy if depth < level]
                hierarchy.append((level, title.strip()))
            section = headings[-1][1].strip()
        sources.append({'chunk_id': f'{document}#{local_id}', 'document': document,
                        'local_chunk_index': local_id, 'section': section,
                        'section_id': section_id, 'section_path': [title for _, title in hierarchy],
                        'content_kind': content_kind(chunk, section, local_id)})
    return sources


def penalty_factor(question, source, config):
    kind = source.get('content_kind', 'body')
    # Lift a penalty when the question itself asks for front matter/references.
    if kind == 'references' and not re.search(r'\b(references|bibliograph\w*|citation\w*|cited|cite|referências)\b', question, re.I):
        return config.reference_weight
    if kind == 'front_matter' and not re.search(r'\b(author\w*|affiliation\w*|title|doi|published|publication|autores?)\b', question, re.I):
        return config.front_matter_weight
    return 1.0


def penalize_order(order, scores, sources, question, config=None):
    config = config or EvidenceConfig()
    adjusted = {i: scores[i] * penalty_factor(question, sources[i], config) for i in order}
    return sorted(order, key=lambda i: (-adjusted[i], i)), adjusted


def continuity_order(order, sources, config=None, limit=None):
    """Expand ranked anchors into source-ordered blocks within the same section.

    Unknown sections are not expanded. Each chunk appears once. Neighbors are
    context evidence, not extra scored retrieval hits or a new model reranking.
    """
    config = config or EvidenceConfig()
    limit = config.max_chunks if limit is None else limit
    groups = {}
    for i, source in enumerate(sources):
        if source.get('section_id', -1) < 0 or not source.get('section'):
            continue
        key = (source['document'], source['section_id'])
        groups.setdefault(key, []).append(i)
    for members in groups.values():
        members.sort(key=lambda i: sources[i].get('local_chunk_index', i))
    membership = {i: (members, position) for members in groups.values() for position, i in enumerate(members)}
    selected, seen = [], set()
    for anchor in order:
        if anchor in seen:
            continue
        members, position = membership.get(anchor, ([anchor], 0))
        if len(members) <= config.small_section_chunks:
            neighbors = members
        else:
            neighbors = members[max(0, position-config.neighbors_before):position+config.neighbors_after+1]
        remaining = limit - len(selected)
        if remaining <= 0:
            break
        # Retain the anchor even when only a few slots remain.
        candidates = [anchor] + sorted((i for i in neighbors if i != anchor), key=lambda i: (abs(i-anchor), i))
        candidates = [i for i in candidates if i not in seen][:remaining]
        for i in sorted(candidates, key=lambda i: sources[i].get('local_chunk_index', i)):
            selected.append(i)
            seen.add(i)
    return selected
