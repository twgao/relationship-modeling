#!/usr/bin/env python3
"""Export complete, readable transcripts from the already-public pilot JSON.

Run: python3 export-conversations.py
Verify without writing: python3 export-conversations.py --check
Uses only the Python standard library. No provider calls or private inputs.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
CASE_NAMES = {"romeo-juliet": "Romeo and Juliet", "susan-george": "Susan and George"}
APPROACHES = {
    "warm_company": "Warm company", "curious_question": "Curious question",
    "playful_levity": "Playful levity", "guarded_exchange": "Guarded exchange",
    "personal_boundary": "Personal boundary", "candid_frustration": "Candid frustration",
    "reflective_concern": "Reflective concern", "angry_confrontation": "Angry confrontation",
}


def number(value):
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def blockquote(value, indent=""):
    return "\n".join(indent + ("> " + line if line else ">") for line in value.split("\n"))


def counts(trajectory):
    encounters = trajectory["encounters"]
    return {
        "attempts": len(encounters),
        "accepted": sum(e["accepted"] for e in encounters),
        "rejected": sum(not e["accepted"] for e in encounters),
        "speech_lines": sum(len(e["transcript"]) for e in encounters),
        "speech_words": sum(len(line["speech"].split()) for e in encounters for line in e["transcript"]),
    }


def validate_source(data):
    """Check saved status, state continuity, evidence attribution, and totals."""
    total = Counter()
    h = data["design"]["step_duration"]
    seen_runs = set()
    for trajectory in data["trajectories"]:
        key = trajectory["case"], trajectory["seed"]
        assert key not in seen_runs
        seen_runs.add(key)
        previous = trajectory["initial_affection"]
        accepted = 0
        for attempt, encounter in enumerate(trajectory["encounters"], 1):
            assert encounter["attempt"] == attempt
            assert encounter["affection_before"] == previous
            if encounter["accepted"]:
                accepted += 1
                assert encounter["status"] == "accepted"
            else:
                assert encounter["status"] == "rejected"
                assert encounter["affection_before"] == encounter["affection_after"]
                assert encounter["native_bonds_before"] == encounter["native_bonds_after"]
            assert encounter["accepted_step"] == accepted
            assert math.isclose(encounter["time"], accepted * h, abs_tol=1e-12)
            transcript = encounter["transcript"]
            assert [line["line"] for line in transcript] == list(range(1, len(transcript) + 1))
            assert all(line["speaker"] in trajectory["characters"] for line in transcript)
            for observation in encounter["observations"]:
                line = transcript[observation["line"] - 1]
                assert observation["quote"] == line["speech"]
                assert observation["speaker"] == line["speaker"]
                assert observation["listener"] != observation["speaker"]
                assert observation["applied"] == encounter["accepted"]
                assert -1 <= observation["warmth"] <= 1
            previous = encounter["affection_after"]
        assert accepted == trajectory["accepted"]
        total.update(counts(trajectory))
    assert len(seen_runs) == 4
    assert total["attempts"] == data["counts"]["recorded_attempts"] == 20
    assert total["accepted"] == data["counts"]["accepted"] == 19
    assert total["rejected"] == data["counts"]["rejected"] == 1
    return total


def render_run(trajectory, run):
    case = CASE_NAMES[trajectory["case"]]
    count = counts(trajectory)
    parts = [
        f"# {case} — run {run}",
        "[All runs](README.md) · [Source data](../fable-pilot-results.json)",
        f"**{count['attempts']} attempted conversations; {count['accepted']} accepted; "
        f"{count['rejected']} rejected.** All {count['speech_lines']} recorded dialogue lines appear below, unchanged.",
        f"Sampler seed: `{trajectory['seed']}`. This seeds the local approach selection, not the language models.",
        "Affection is the experiment's separate −1 to +1 score, not Fable's ordinary bond score. "
        "Values below are rounded to six decimal places. Warmth ratings are the appraiser's interpretations of speech. "
        "The sampled approach is a candidate label, not a discovered personality trait or necessarily the most likely choice.",
    ]
    for encounter in trajectory["encounters"]:
        status = "accepted" if encounter["accepted"] else "REJECTED"
        parts.append(f"## Attempt {encounter['attempt']} — {status}")
        if not encounter["accepted"]:
            parts.append("**REJECTED — no state or model-time update.** "
                         f"Stage: `{encounter['failure_stage']}`. Reason: `{encounter['reason']}`. "
                         "The generated dialogue is retained for inspection; its warmth ratings were not applied.")
        parts.append(f"Accepted step after this attempt: **{encounter['accepted_step']}**. "
                     f"Model time: **{number(encounter['time'])}**. "
                     f"Focal character: **{encounter['focal_character']}**. "
                     f"Sampled approach: **{APPROACHES[encounter['selected_intent']]}** "
                     f"(`{encounter['selected_intent']}`).")
        table = ["| Character | Affection before | Affection after |",
                 "| --- | ---: | ---: |"]
        for index, character in enumerate(trajectory["characters"]):
            table.append(f"| {character} | {number(encounter['affection_before'][index])} "
                         f"| {number(encounter['affection_after'][index])} |")
        parts.append("\n".join(table))
        parts.append("### Dialogue")
        for line in encounter["transcript"]:
            parts.append(blockquote(f"**{line['speaker']} (line {line['line']}):** {line['speech']}"))
        parts.append("### Warmth ratings")
        for observation in encounter["observations"]:
            applied = "applied" if observation["applied"] else "**not applied — encounter rejected**"
            parts.append(f"- **{observation['listener']} hears {observation['speaker']}:** "
                         f"warmth **{number(observation['warmth'])}**; {applied}. "
                         f"Evidence: line {observation['line']}.\n\n"
                         + blockquote(observation["quote"], "  "))
    return "\n\n".join(parts) + "\n"


def parse_dialogue(markdown):
    """Recover speech from rendered Markdown independently of the writer."""
    result, current, section = {}, None, None
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        text = lines[index]
        heading = re.fullmatch(r"## Attempt (\d+) — (?:accepted|REJECTED)", text)
        if heading:
            current = int(heading.group(1))
            result[current] = []
            section = None
        elif text.startswith("### "):
            section = text
        elif section == "### Dialogue":
            speech = re.fullmatch(r"> \*\*(.+) \(line (\d+)\):\*\* (.*)", text)
            if speech:
                segments = [speech.group(3)]
                while index + 1 < len(lines) and (lines[index + 1] == ">" or lines[index + 1].startswith("> ")):
                    index += 1
                    segments.append(lines[index][2:] if lines[index] != ">" else "")
                result[current].append({"line": int(speech.group(2)), "speaker": speech.group(1),
                                        "speech": "\n".join(segments)})
        index += 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify existing exports without writing.")
    args = parser.parse_args()
    source = ROOT / "fable-pilot-results.json"
    directory = ROOT / "conversations"
    data = json.loads(source.read_text())
    total = validate_source(data)
    files, rows, by_case = {}, [], Counter()
    for trajectory in data["trajectories"]:
        case = trajectory["case"]
        by_case[case] += 1
        run = by_case[case]
        filename = f"{case}-run-{run}.md"
        files[filename] = render_run(trajectory, run)
        count = counts(trajectory)
        rows.append(f"| [{CASE_NAMES[case]} — run {run}]({filename}) | {trajectory['seed']} | "
                    f"{count['accepted']}/{count['attempts']} | {count['speech_lines']} | {count['speech_words']} |")
        expected = {e["attempt"]: e["transcript"] for e in trajectory["encounters"]}
        assert parse_dialogue(files[filename]) == expected

    files["README.md"] = "\n\n".join([
        "# Complete Fable conversation transcripts",
        "These are all the generated conversations from the recorded pilot: **20 attempts, 19 accepted, "
        "1 rejected, 53 dialogue lines**. They are synthetic conversations from Fable's Jev → joint writer → "
        "appraisal pipeline, not quotations from the original fictional works. No dialogue has been extended or rewritten.",
        "| Run | Sampler seed | Accepted/attempted | Dialogue lines | Dialogue words |\n"
        "| --- | ---: | ---: | ---: | ---: |\n" + "\n".join(rows),
        "Each file includes every attempt in order, the complete dialogue, the sampled approach, affection "
        "before and after, and the appraiser's warmth ratings with their quoted evidence. Romeo and Juliet, "
        "run 2, attempt 2 was rejected: it changed neither the state nor model time, and its ratings were not applied.",
        "The approach labels are candidates supplied to Jev. Selection is probabilistic; a selected label "
        "is not necessarily the highest-rated candidate or a discovered personality trait. The warmth scores "
        "are automated interpretations, not independent measurements of the characters' feelings.",
        "Models: `jev-1.13.0` rates approaches; `moonshot.kimi-k2-thinking` writes both voices; "
        "`us.meta.llama4-scout-17b-instruct-v1:0` appraises the result. Sampler seeds control local approach "
        "selection only. Accepted encounters advance model time by 0.5; rejected ones do not.",
        "The [public source JSON](../fable-pilot-results.json) retains the numeric data at full precision. "
        "Displayed affection values are rounded to six decimal places; dialogue and evidence quotes are verbatim. "
        "Dialogue word counts use whitespace-separated words and include the rejected attempt.",
        "To regenerate these pages, run `python3 export-conversations.py` from the supplement directory. "
        "Run `python3 export-conversations.py --check` to verify all exported speech against the JSON without writing files.",
    ]) + "\n"
    if not args.check:
        directory.mkdir(parents=True, exist_ok=True)
        for filename, content in files.items():
            (directory / filename).write_text(content)
    for filename, expected in files.items():
        actual = (directory / filename).read_text()
        assert actual == expected, f"Export differs from source: {filename}"
        if filename != "README.md":
            assert parse_dialogue(actual) == parse_dialogue(expected)
    print(json.dumps({"verified": True, "runs": len(data["trajectories"]), **total,
                      "accepted_speech_lines": sum(len(e["transcript"]) for t in data["trajectories"]
                                                   for e in t["encounters"] if e["accepted"]),
                      "markdown_files": sorted(files)}, indent=2))


if __name__ == "__main__":
    main()
