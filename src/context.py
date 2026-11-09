"""Pack selected evidence without changing source labels or context limits."""

if __package__:
    from .settings import MAX_CONTEXT_TOKENS
else:
    from settings import MAX_CONTEXT_TOKENS


def build_context(chunks, order, tokenizer, sources=None, max_tokens=MAX_CONTEXT_TOKENS):
    prefix = "Context extracted from a blind search over the corpus:\n\n"
    suffix = "\n\n---\n\n"
    selected = []
    for index in order:
        label = f"[Fragment {len(selected) + 1}]"
        if sources is not None:
            source = sources[index]
            label += f" [Source: {source['chunk_id']}]"
            if source.get("section"):
                label += f" [Section: {source['section']}]"

        def context_with(text):
            return prefix + "\n\n".join([*selected, f"{label}\n{text}"]) + suffix

        chunk = chunks[index]
        if len(tokenizer.encode(context_with(chunk))) > max_tokens:
            if not selected:
                low, high = 0, len(chunk)
                while low < high:
                    middle = (low + high + 1) // 2
                    if len(tokenizer.encode(context_with(chunk[:middle]))) <= max_tokens:
                        low = middle
                    else:
                        high = middle - 1
                if low and len(tokenizer.encode(context_with(chunk[:low]))) <= max_tokens:
                    selected.append(f"{label}\n{chunk[:low]}")
            break
        selected.append(f"{label}\n{chunk}")
    return prefix + "\n\n".join(selected) + suffix if selected else ""
