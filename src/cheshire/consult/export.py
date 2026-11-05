"""Markdown and JSON export of a consultation (consult.md 3, region 10).

Pure functions over the session view: requirement, facts, result, rationale and choice
records. Nothing is ranked: solutions are listed alphabetically with their state labels.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

_EXPORT_KEYS = (
    "id",
    "title",
    "owner",
    "revision",
    "identified_abbs",
    "facts",
    "answered_unknown",
    "evaluation",
    "rationale",
    "choices",
    "feedback",
)


def to_json(view: dict[str, Any]) -> str:
    payload = {k: view.get(k) for k in _EXPORT_KEYS}
    payload["catalog"] = view["catalog"]
    return json.dumps(payload, indent=2, ensure_ascii=False, default=_default)


def _default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not serialisable: {type(value).__name__}")


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _stamp(value: Any) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if isinstance(value, datetime) else str(value)


def to_markdown(view: dict[str, Any]) -> str:
    catalog = view["catalog"]
    abb_names = {a["id"]: a["name"] for a in catalog["abbs"]}
    sbb_names = {s["id"]: s["name"] for s in catalog["sbbs"]}
    out: list[str] = [f"# {view['title']}", ""]
    out += [f"Owner: {view['owner']} · revision {view['revision']['number']}", ""]
    out += [
        "## Requirement",
        "",
        *(f"> {line}" for line in view["revision"]["requirement_text"].splitlines()),
        "",
    ]

    if view["facts"] or view["answered_unknown"]:
        out += ["## What was understood", "", "| Attribute | Value | Source |", "|---|---|---|"]
        for attr, fact in sorted(view["facts"].items()):
            value = fact["value"] if isinstance(fact["value"], str) else ", ".join(fact["value"])
            out.append(f"| {_cell(attr)} | {_cell(value)} | {fact['source']} |")
        for attr in view["answered_unknown"]:
            out.append(f"| {_cell(attr)} | unknown | answered |")
        out.append("")

    evaluation = view["evaluation"]
    if evaluation is None:
        out += ["## Result", "", "No building block was identified in this requirement.", ""]
    else:
        result = evaluation["result"]
        out += ["## Result", ""]
        for abb in result["abbs"]:
            out += [f"### {abb_names.get(abb['id'], abb['id'])} (`{abb['id']}`)", ""]
            strength = f", {abb['strength']}" if abb.get("strength") else ""
            validation = f", rules {abb['validation']}" if abb.get("validation") else ""
            out += [
                f"Activation: {abb['activation']}{strength}{validation}."
                f" Coverage: {abb['coverage']}.",
                "",
            ]
            if abb["coverage"] == "gap":
                out += ["No solution is registered in the catalog for this building block.", ""]
            for sbb in sorted(abb["sbbs"], key=lambda s: s["id"]):
                line = (
                    f"- **{sbb['name']}** (`{sbb['id']}`): {sbb['result']},"
                    f" catalog state {sbb['state']}"
                )
                if sbb["status"] != "validated":
                    line += f", {sbb['status']}"
                if sbb.get("reason"):
                    line += f" — {sbb['reason']}"
                out.append(line)
            if abb["sbbs"]:
                out.append("")
        if result["pending_questions"]:
            out += ["### Open questions", ""]
            for q in result["pending_questions"]:
                affects = ", ".join(abb_names.get(i, i) for i in q["impact"])
                out.append(f"- {q['question']} (changes: {affects})")
            out.append("")

    rationale = view["rationale"]
    if rationale is not None:
        out += ["## Rationale", ""]
        if rationale["outdated"]:
            out += ["_Outdated: the answers changed after this explanation was written._", ""]
        # One bullet per sentence; the trace entries it rests on go on their own indented
        # line as code spans, so Markdown never reads `[abb:x]` as a link reference.
        for sentence in rationale["content"]["sentences"]:
            flag = "" if sentence.get("verified", True) else " _(unverified)_"
            out.append(f"- {sentence['text']}{flag}")
            if sentence["refs"]:
                out.append(
                    "  <sub>Based on: " + ", ".join(f"`{r}`" for r in sentence["refs"]) + "</sub>"
                )
        out.append("")

    out += ["## Choices", ""]
    if not view["choices"]:
        out += ["No choice has been recorded.", ""]
    for c in view["choices"]:
        what = {
            "chosen": f"chose {sbb_names.get(c['sbb'], c['sbb'])}",
            "decide_later": "decides later",
            "outside_catalog": "handles it outside the catalog",
        }[c["kind"]]
        line = f"- {abb_names.get(c['abb'], c['abb'])}: {c['actor']} {what} ({_stamp(c['at'])})"
        if c["sbb_result"] == "conditional":
            line += "; conditional"
        if c["reason"]:
            line += f". Reason: {c['reason']}"
        out.append(line)
        if c["unresolved_questions"]:
            out.append(f"  - Unresolved when chosen: {', '.join(c['unresolved_questions'])}")
    out.append("")

    if view["feedback"]:
        out += ["## Feedback", ""]
        for f in view["feedback"]:
            target = abb_names.get(f["abb"], f["abb"]) if f["abb"] else "whole result"
            out.append(f"- {f['kind']} ({target}), {f['author']}: {f['text']}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
