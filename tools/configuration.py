"""Translate flat JSON pipeline settings to validated argparse arguments."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_with_config(parser, argv):
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--config", type=Path)
    known, _ = bootstrap.parse_known_args(argv)
    if known.config is None:
        return parser.parse_args(argv)
    values = json.loads(known.config.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        parser.error("Pipeline config must be a JSON object")
    actions = {action.dest: action for action in parser._actions if action.dest not in ("help", "config")}
    unknown = set(values) - set(actions)
    if unknown:
        parser.error(f"Unknown configuration keys: {sorted(unknown)}")
    tokens = []
    for name, value in values.items():
        action = actions[name]
        if value is None:
            if action.default is not None:
                parser.error(f"{name} cannot be null")
            continue
        if isinstance(action, (argparse.BooleanOptionalAction, argparse._StoreTrueAction, argparse._StoreFalseAction)):
            if type(value) is not bool:
                parser.error(f"{name} must be a JSON boolean")
            candidates = [a for a in parser._actions if a.dest == name]
            if isinstance(action, argparse.BooleanOptionalAction):
                tokens.append(action.option_strings[0 if value else 1])
            else:
                match = next((a for a in candidates if isinstance(a, argparse._StoreTrueAction) and value
                              or isinstance(a, argparse._StoreFalseAction) and not value), None)
                if match:
                    tokens.append(match.option_strings[0])
                elif value != action.default:
                    parser.error(f"No flag supports {name}={value}")
            continue
        many = action.nargs in ("+", "*")
        if many != isinstance(value, list):
            parser.error(f"Invalid scalar/list value for {name}")
        items = value if many else [value]
        if many and not items:
            if name == "preserve_words":
                continue
            parser.error(f"{name} cannot be an empty list")
        if action.type is Path:
            if not all(isinstance(item, str) for item in items):
                parser.error(f"{name} paths must be strings")
            items = [str((ROOT / item).resolve()) for item in items]
        tokens += [action.option_strings[0], *[str(item) for item in items]]
    # Explicit command-line arguments override values from the JSON file.
    return parser.parse_args(tokens + list(argv))
