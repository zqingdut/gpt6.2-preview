#!/usr/bin/env python3
"""Render README.md from data/cases.json using templates/README.md.j2."""
import json

from jinja2 import Environment, FileSystemLoader

CATEGORIES = {
    "demo_3d": "🧊 3D 与游戏演示 (3D & Game Demos)",
    "sighting": "🔍 灰度目击 (Gray-rollout Sightings)",
    "signal": "📡 信号与讨论 (Signals & Discussion)",
}

CATEGORIES_EN = {
    "demo_3d": "🧊 3D & Game Demos",
    "sighting": "🔍 Gray-rollout Sightings",
    "signal": "📡 Signals & Discussion",
}


def cell(value) -> str:
    """Sanitize a value for use inside a Markdown table cell."""
    if value is None:
        return ""
    return str(value).replace("|", "¦").replace("\n", " ").strip()


def cost(value) -> str:
    """Format a cost value: 11.66 -> $11.66, '~20' -> ~$20, '' -> ''."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return f"${value:g}" if float(value) % 1 else f"${value}"
    s = str(value).strip()
    if s.startswith("~"):
        return "~$" + s[1:]
    if "$" in s:
        return s
    return "$" + s


def build():
    with open("data/cases.json", "r", encoding="utf-8") as f:
        cases = json.load(f)

    env = Environment(
        loader=FileSystemLoader("templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["cell"] = cell
    env.filters["cost"] = cost
    template = env.get_template("README.md.j2")
    md = template.render(cases=cases, categories=CATEGORIES)
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(md)
    print(f"README.md rendered from {len(cases)} cases.")

    template_en = env.get_template("README_EN.md.j2")
    md_en = template_en.render(cases=cases, categories_en=CATEGORIES_EN)
    with open("README_EN.md", "w", encoding="utf-8") as f:
        f.write(md_en)
    print(f"README_EN.md rendered from {len(cases)} cases.")


if __name__ == "__main__":
    build()
