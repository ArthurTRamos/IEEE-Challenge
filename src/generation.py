"""Answer-model loading is isolated from document and retrieval experiments."""

if __package__:
    from .prompts import SYSTEM_PROMPT, build_user_message
    from .runtime import resolve_device
    from .settings import MAX_NEW_TOKENS
else:
    from prompts import SYSTEM_PROMPT, build_user_message
    from runtime import resolve_device
    from settings import MAX_NEW_TOKENS

_models = {}


def load_model(model_id, device="cuda"):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    device = resolve_device(device)
    key = (model_id, device)
    if key not in _models:
        tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_id, dtype=torch.bfloat16 if device == "cuda" else torch.float32,
            device_map=device, local_files_only=True,
        )
        model.eval()
        _models[key] = (tokenizer, model)
    return _models[key]


def generate_answer(question, context, tokenizer, model, max_new_tokens=MAX_NEW_TOKENS):
    import torch
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(question, context)}]
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt", return_dict=True,
    ).to(model.device)
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                                pad_token_id=tokenizer.pad_token_id)
    return tokenizer.decode(output[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True).strip()
