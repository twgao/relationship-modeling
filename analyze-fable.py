# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["numpy==2.2.6", "scipy==1.15.3", "matplotlib==3.10.3"]
# ///
"""Export fictional pilot results through a whitelist and draw descriptive figures.

No network requests. Raw prompts and private implementation sources are never exported.
After the provider process has ended:
    uv run analyze-fable.py --input RUN_DIRECTORY --provider-finished
The public JSON is sufficient to redraw the figures:
    uv run analyze-fable.py --from-export fable-pilot-results.json
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np


ROOT = Path(__file__).resolve().parent
CASE_NAMES = {"romeo-juliet": ["Romeo", "Juliet"], "susan-george": ["Susan", "George"]}
COEFFICIENTS = {
    "romeo-juliet": [{"a": 0, "b": 1}, {"a": 0, "b": -1}],
    "susan-george": [{"a": 1, "b": 2}, {"a": -1, "b": -1}],
}
INTENT_LABELS = {
    "warm_company": "Company", "curious_question": "Curiosity",
    "playful_levity": "Joke", "guarded_exchange": "Guarded",
    "personal_boundary": "Boundary", "candid_frustration": "Frustration",
    "reflective_concern": "Concern", "angry_confrontation": "Anger",
}
MODELS = {
    "rating": "jev-1.13.0", "dialogue": "moonshot.kimi-k2-thinking",
    "appraisal": "us.meta.llama4-scout-17b-instruct-v1:0",
}
FAILURE_REASONS = {
    "missing_key", "aborted", "deadline", "invalid_input", "provider_unavailable",
    "invalid_ratings", "no_eligible_candidate", "invalid_dialogue", "invalid_appraisal",
    "selection_not_preserved", "unsupported_completion", "ungrounded_consequences",
    "completion_failed", "invalid-research-observation", "incomplete-record",
}
STAGES = {"configuration", "rating", "dialogue", "appraisal"}
COLORS = ["#176F83", "#C66539"]
INK, MUTED, RED = "#20313C", "#5C6D76", "#AB344D"
REQUEST_RE = re.compile(r"^(romeo-juliet|susan-george)-(\d+)-(\d+)-call-(\d+)-request\.json$")


def read(path: Path):
    return json.loads(path.read_text())


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite numeric result")
    return value


def close(left, right):
    if not np.allclose(left, right, atol=2e-12, rtol=2e-12):
        raise ValueError("Independent numerical replay did not match the saved result")


def held(r, u, coefficient, h):
    a, b = coefficient["a"], coefficient["b"]
    phi = h if a == 0 else math.expm1(a * h) / a
    raw = math.exp(a * h) * r + b * phi * u
    return {"after": max(-1, min(1, raw)), "unclipped": raw, "clipped": abs(raw) > 1}


def continuous(case, initial, times):
    t = np.asarray(times)
    x, y = initial
    if case == "romeo-juliet":
        return np.array([x * np.cos(t) + y * np.sin(t), y * np.cos(t) - x * np.sin(t)])
    return np.array([x * np.cos(t) + (x + 2 * y) * np.sin(t), y * np.cos(t) - (x + y) * np.sin(t)])


def parse_completion(text):
    if not isinstance(text, str):
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def native_bonds(context, ids):
    people = {person["characterId"]: person for person in context["participants"]}
    return [finite(next(edge["score"] for edge in people[own]["relationships"]
                        if edge["toCharacterId"] == ids[1 - i])) for i, own in enumerate(ids)]


def safe_transcript(value, names):
    """Copy only attributable generated speech, never the containing completion."""
    if not isinstance(value, dict) or not isinstance(value.get("exchanges"), list):
        return []
    rows = []
    for index, item in enumerate(value["exchanges"], 1):
        if not isinstance(item, dict) or item.get("speaker") not in names or not isinstance(item.get("speech"), str):
            return []
        if len(item["speech"]) > 4000:
            raise ValueError("Unexpectedly long speech; inspect privately before export")
        rows.append({"line": index, "speaker": item["speaker"], "speech": item["speech"]})
    return rows


def distribution(response):
    """Recompute the frozen expected-score / floor-one / square policy."""
    if not isinstance(response, dict) or response.get("model") != MODELS["rating"]:
        return None
    answers = response.get("answers", {})
    scores = {}
    for intent in INTENT_LABELS:
        rating = answers.get(intent, {})
        probabilities = rating.get("probabilities", {})
        if rating.get("type") != "score" or set(probabilities) != {"0", "1", "2", "3"}:
            return None
        mass = [finite(probabilities[str(i)]) for i in range(4)]
        if any(p < 0 for p in mass) or sum(mass) <= 0:
            return None
        scores[intent] = sum(i * p for i, p in enumerate(mass)) / sum(mass)
    weights = {key: score**2 if score >= 1 else 0 for key, score in scores.items()}
    if sum(weights.values()) == 0:
        return None
    return {"expected_scores": scores, "probabilities": {key: w / sum(weights.values()) for key, w in weights.items()}}


def read_calls(directory, manifest):
    """Read private request files for verification; return only selected output fields."""
    grouped = defaultdict(list)
    accounting = Counter()
    usage = {stage: {"input_tokens": 0, "output_tokens": 0, "requests_with_usage": 0} for stage in MODELS}
    flow = Counter()
    for path in sorted(directory.glob("*-call-*-request.json")):
        match = REQUEST_RE.fullmatch(path.name)
        if not match:
            raise ValueError("Unexpected call filename")
        case, seed, attempt, _ = match.groups()
        request = read(path)
        stage = request["stage"]
        if stage not in MODELS or request["modelId"] != MODELS[stage]:
            raise ValueError("Unreviewed provider model or stage")
        response_path = path.with_name(path.name.replace("-request.json", "-response.json"))
        response = read(response_path) if response_path.exists() else {}
        accounting[stage] += 1
        item = {"stage": stage}
        if stage == "rating":
            raw = response.get("structuredOutput")
            item["distribution"] = distribution(raw)
            raw_usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
            reported = {"inputTokens": raw_usage.get("input_tokens"), "outputTokens": raw_usage.get("output_tokens")}
            current = request.get("payload", {}).get("state", {}).get("context", {}).get("currentState", {})
            own = current.get("researchAffection", {})
            # This numeric field is used for a data-flow equality check only.
            item["rating_affection"] = own.get("value")
            flow["rating_fields_checked"] += 1
        else:
            if request.get("settings") != manifest["settings"][stage]:
                raise ValueError("Provider settings drift")
            reported = response.get("usage") or {}
            parsed = parse_completion(response.get("finalText"))
            if stage == "dialogue":
                item["transcript"] = safe_transcript(parsed, CASE_NAMES[case])
                marker = "Research-only private affective states: "
                message = request.get("userMessage", "")
                if marker in message:
                    extra, _ = json.JSONDecoder().raw_decode(message.split(marker, 1)[1])
                    item["writer_affection"] = {p["characterId"]: p["researchAffection"] for p in extra}
                flow["writer_fields_checked"] += 1
            else:
                if "researchAffection" in request.get("userMessage", ""):
                    raise ValueError("Private numerical affection unexpectedly entered appraisal")
                flow["appraisal_without_numeric_research_state"] += 1
        if all(isinstance(reported.get(key), (float, int)) for key in ["inputTokens", "outputTokens"]):
            usage[stage]["input_tokens"] += finite(reported["inputTokens"])
            usage[stage]["output_tokens"] += finite(reported["outputTokens"])
            usage[stage]["requests_with_usage"] += 1
        grouped[(case, int(seed), int(attempt))].append(item)
    # No request dictionaries or model prompts leave this function.
    return grouped, dict(accounting), usage, flow


def extract(directory):
    manifest = read(directory / "manifest.json")
    raw_controls = read(directory / "controls.json")
    summary_path = directory / "summary.json"
    summary = read(summary_path) if summary_path.exists() else None
    if manifest.get("mode") != "live" or manifest.get("models") != MODELS:
        raise ValueError("Expected the frozen live pilot, not a dry plan or another model")
    if manifest.get("initialDeviation") != 0 or manifest.get("gaussianNoise") is not False:
        raise ValueError("Unreviewed noise design")
    seeds = [int(seed) for seed in manifest["seeds"]]
    steps, h = int(manifest["stepsPerTrajectory"]), finite(manifest["h"])
    initial = [finite(value) for value in manifest["initialAffection"]]
    specs = {item["id"]: item for item in manifest["cases"]}
    if set(specs) != set(CASE_NAMES):
        raise ValueError("Unreviewed case")
    for case in CASE_NAMES:
        if specs[case]["names"] != CASE_NAMES[case] or specs[case]["coefficients"] != COEFFICIENTS[case]:
            raise ValueError("Response law differs from the frozen design")

    controls = {}
    for raw in raw_controls:
        case = raw["caseId"]
        own_held, own_self = initial[:], initial[:]
        points = []
        for index, point in enumerate(raw["points"]):
            if index:
                prior = own_held[:]
                own_held = [held(prior[i], prior[1 - i], COEFFICIENTS[case][i], h)["after"] for i in range(2)]
                own_self = [held(own_self[i], 0, COEFFICIENTS[case][i], h)["after"] for i in range(2)]
            close(point["continuousUnbounded"], continuous(case, initial, index * h))
            close(point["heldOracleClipped"], own_held)
            close(point["selfOnlyClipped"], own_self)
            points.append({"accepted_step": index, "time": index * h,
                           "continuous_class": [finite(x) for x in point["continuousUnbounded"]],
                           "held_partner_oracle": own_held[:], "self_only": own_self[:]})
        if len(points) != steps + 1:
            raise ValueError("Incomplete mechanical controls")
        controls[case] = points

    calls, request_counts, token_usage, flow = read_calls(directory, manifest)
    rows = {}
    for path in directory.glob("*-encounter.json"):
        raw = read(path)
        key = (raw["caseId"], int(raw["seed"]), int(raw["step"]))
        if key in rows:
            raise ValueError("Duplicate encounter")
        rows[key] = raw
    trajectories, complete_count, rejected_count, incomplete_count = [], 0, 0, 0
    bound_count = 0
    for case, names in CASE_NAMES.items():
        ids = [f"{case}-{name.lower()}" for name in names]
        for seed in seeds:
            previous = initial[:]
            accepted_clock, records = 0, []
            for attempt in range(1, steps + 1):
                key = (case, seed, attempt)
                stages = calls.get(key, [])
                raw = rows.get(key)
                if raw is None and not stages:
                    continue
                if raw is None:
                    records.append({"attempt": attempt, "accepted": None, "status": "incomplete-record",
                                    "last_known_accepted_step": accepted_clock,
                                    "last_known_time": accepted_clock * h,
                                    "rating": next((s.get("distribution") for s in stages if s["stage"] == "rating"), None),
                                    "transcript": next((s.get("transcript", []) for s in stages if s["stage"] == "dialogue"), []),
                                    "recorded_requests": len(stages)})
                    incomplete_count += 1
                    continue
                result = raw["result"]
                before = [finite(raw["beforeAffection"][who]) for who in ids]
                after = [finite(raw["afterAffection"][who]) for who in ids]
                close(before, previous)
                accepted = raw["accepted"] is True
                if accepted:
                    accepted_clock += 1
                    complete_count += 1
                else:
                    rejected_count += 1
                    close(after, before)
                if raw["acceptedStep"] != accepted_clock:
                    raise ValueError("Accepted-update clock mismatch")
                close(raw["modelTime"], accepted_clock * h)
                decision = result.get("decision", {})
                selection = decision.get("candidateId")
                if not selection:
                    selection = next((event.get("candidateId") for event in raw["status"]
                                      if event.get("stage") == "rating" and event.get("status") == "completed"), None)
                if selection is not None and selection not in INTENT_LABELS:
                    raise ValueError("Unexpected reaction ID")
                ratings = next((stage.get("distribution") for stage in stages if stage["stage"] == "rating"), None)
                if decision.get("alternatives") and ratings:
                    close([alt["probability"] for alt in decision["alternatives"]],
                          [ratings["probabilities"][alt["candidateId"]] for alt in decision["alternatives"]])
                transcript = safe_transcript(result.get("interaction"), names)
                if not transcript:
                    transcript = next((stage.get("transcript", []) for stage in stages if stage["stage"] == "dialogue"), [])
                focal = ids.index(raw["focalId"])
                for stage in stages:
                    if stage["stage"] == "rating":
                        close(stage.get("rating_affection"), before[focal])
                        flow["rating_state_matches"] += 1
                    if stage["stage"] == "dialogue":
                        sent = stage.get("writer_affection", {})
                        close([sent.get(who) for who in ids], before)
                        flow["writer_state_matches"] += 1
                observations = []
                for observation in raw.get("observations", []) or []:
                    if not isinstance(observation, dict):
                        continue
                    listener, speaker = observation.get("listenerId"), observation.get("speakerId")
                    line_id = observation.get("evidenceLineId", "")
                    if listener not in ids or speaker not in ids or listener == speaker or not re.fullmatch(r"line-\d+", line_id):
                        continue
                    line_number = int(line_id.split("-")[1])
                    quote = observation.get("quote")
                    line = next((line for line in transcript if line["line"] == line_number), None)
                    grounded = bool(line and line["speaker"] == names[ids.index(speaker)] and line["speech"] == quote)
                    value = observation.get("value")
                    if not isinstance(value, (float, int)) or not math.isfinite(value) or not -1 <= value <= 1:
                        continue
                    # Never export a purported quotation that does not match actual generated speech.
                    observations.append({"listener": names[ids.index(listener)], "speaker": names[ids.index(speaker)],
                                         "warmth": value, "line": line_number,
                                         "quote": line["speech"] if grounded else None,
                                         "matches_utterance": grounded, "applied": accepted and grounded})
                updates = []
                if accepted:
                    if len(observations) != 2 or not all(o["matches_utterance"] for o in observations):
                        raise ValueError("Accepted observation lacks exact utterance evidence")
                    for i, name in enumerate(names):
                        observation = next(o for o in observations if o["listener"] == name)
                        update = held(before[i], observation["warmth"], COEFFICIENTS[case][i], h)
                        saved = next(u for u in raw["updates"] if u["characterId"] == ids[i])
                        close([update["after"], update["unclipped"]], [after[i], saved["unclipped"]])
                        if update["clipped"] != saved["boundHit"]:
                            raise ValueError("Clipping flag mismatch")
                        bound_count += int(update["clipped"])
                        updates.append({"character": name, "before": before[i], "warmth": observation["warmth"],
                                        **update, "change": after[i] - before[i]})
                reason = None if accepted else result.get("reason", "invalid-research-observation")
                if reason is not None and reason not in FAILURE_REASONS:
                    raise ValueError("Unreviewed failure reason")
                failure_stage = None if accepted else result.get("stage", "appraisal")
                if failure_stage is not None and failure_stage not in STAGES:
                    raise ValueError("Unreviewed failure stage")
                native_before = native_bonds(raw["beforeContext"], ids)
                native_after = native_bonds(raw["afterContext"], ids)
                if not accepted:
                    close(native_before, native_after)
                records.append({"attempt": attempt, "accepted_step": accepted_clock, "time": accepted_clock * h,
                                "accepted": accepted, "status": "accepted" if accepted else "rejected",
                                "failure_stage": failure_stage, "reason": reason, "focal_character": names[focal],
                                "affection_before": before, "affection_after": after,
                                "native_bonds_before": native_before, "native_bonds_after": native_after,
                                "selected_intent": selection, "rating": ratings,
                                "categorical_draws": [finite(d) for d in raw["draws"]],
                                "transcript": transcript, "observations": observations, "updates": updates,
                                "matched_mechanical_control": controls[case][accepted_clock],
                                "recorded_requests": len(stages)})
                previous = after
            trajectories.append({"case": case, "seed": seed, "characters": names,
                                 "planned_attempts": steps, "attempted": len(records),
                                 "accepted": sum(row.get("accepted") is True for row in records),
                                 "initial_affection": initial, "encounters": records})

    recorded_calls = sum(request_counts.values())
    if summary is not None:
        if summary["providerRequests"] != recorded_calls or summary["accepted"] != complete_count or summary["encountersAttempted"] != len(rows):
            raise ValueError("Final summary does not match individual records")
    planned = len(CASE_NAMES) * len(seeds) * steps
    estimates = {"rating": (0.042, 0), "dialogue": (0.60, 2.50), "appraisal": (0.17, 0.66)}
    known_cost = sum((counts["input_tokens"] * estimates[stage][0] + counts["output_tokens"] * estimates[stage][1]) / 1e6
                     for stage, counts in token_usage.items())
    return {
        "format_version": 1,
        "scope": "Synthetic, isolated Fable research pilot with real provider-generated dialogue; no player-world writes.",
        "design": {
            "models": MODELS, "region": "us-east-1",
            "settings": {stage: {"temperature": finite(manifest["settings"][stage]["temperature"]),
                                  "maximum_output_tokens": int(manifest["settings"][stage]["maxTokens"]), "top_p": 0.9}
                         for stage in ["dialogue", "appraisal"]},
            "seeds": seeds, "seed_scope": "Our categorical sampler only; provider language and ratings are not deterministically seeded.",
            "planned_runs_per_pair": len(seeds), "attempts_per_run": steps, "step_duration": h,
            "initial_affection": initial, "affection_bounds": [-1, 1], "initial_variation": 0, "gaussian_noise": False,
            "reaction_policy": {"minimum_expected_score": 1, "weight_power": 2},
            "update_equation": "r_next = clip(exp(a*h)*r + b*phi(a,h)*u, -1, 1); phi=h if a=0, otherwise expm1(a*h)/a.",
            "update_meaning": "Expressed warmth u is held constant within one accepted interval. This is exact for held input, not for continuous access to the partner's hidden state.",
            "clock": "Only accepted encounters advance model time. Rejected attempts preserve both research affection and native bonds.",
            "characters": [{"case": case, "names": CASE_NAMES[case], "coefficients": COEFFICIENTS[case]} for case in CASE_NAMES],
        },
        "counts": {"planned_encounters": planned, "recorded_attempts": complete_count + rejected_count + incomplete_count,
                   "accepted": complete_count, "rejected": rejected_count, "incomplete_records": incomplete_count,
                   "not_attempted": planned - complete_count - rejected_count - incomplete_count,
                   "planned_maximum_provider_calls": int(manifest["maximumProviderRequests"]),
                   "recorded_provider_calls": recorded_calls, "calls_by_stage": request_counts,
                   "person_updates_clipped": bound_count, "final_summary_present": summary is not None,
                   "stopped_early": bool(summary["stoppedEarly"]) if summary else None},
        "accounting": {"reported_usage": token_usage, "requests_without_usage": recorded_calls - sum(x["requests_with_usage"] for x in token_usage.values()),
                       "price_derived_cost_of_reported_usage_usd": known_cost, "actual_invoice_cost": None,
                       "planned_reservation_usd": finite(manifest["budget"]["fullPlanReservationUsd"])},
        "data_flow_verification": {**dict(flow), "interpretation": "Equality checks establish that saved states entered later requests. They do not establish a causal effect on generated dialogue."},
        "mechanical_controls": [{"case": case, "generated_dialogue": False, "points": controls[case]} for case in CASE_NAMES],
        "trajectories": trajectories,
        "limits": [
            "Two planned runs per pair and at most five attempted encounters per run: no population frequency, confidence interval, or full-cycle claim.",
            "Affection, coefficients, and clipping are new authored research mechanics. Native broad relationship scores remain separate.",
            "Warmth scores are uncalibrated automated expression judgments, not measurements of another person's hidden feelings.",
            "The joint writer sees both private numerical states; character knowledge boundaries are prompt instructions, not independent agent processes.",
            "The appraiser sees the selected intention and context; the warmth judgment is not blinded.",
            "Continuous, held-partner, and self-only controls are mechanical calculations, not regenerated conversations or a causal ablation.",
            "Acceptance verifies the implemented checks; it is not proof of narrative truth, believable emotion, or human engagement.",
        ],
    }


def style():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 11,
                         "axes.labelsize": 10, "axes.labelcolor": INK, "text.color": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": "#BAC5CB",
                         "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "axes.facecolor": "white",
                         "savefig.facecolor": "white", "svg.fonttype": "none"})


def save_figure(fig, stem):
    directory = ROOT / "figures"
    directory.mkdir(exist_ok=True)
    fig.savefig(directory / f"{stem}.png", dpi=190, bbox_inches="tight", pad_inches=0.15)
    svg = directory / f"{stem}.svg"
    fig.savefig(svg, bbox_inches="tight", pad_inches=0.15, metadata={"Date": None})
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
    plt.close(fig)


def feedback_plot(data):
    design = data["design"]
    seeds, h, steps = design["seeds"], design["step_duration"], design["attempts_per_run"]
    fig, axes = plt.subplots(2, len(seeds), figsize=(12.6, 8.8), sharex=True, sharey=True, squeeze=False)
    fig.subplots_adjust(top=0.78, bottom=0.17, hspace=0.4, wspace=0.13)
    counts = data["counts"]
    fig.suptitle("Affection during the conversation pilot", x=0.065, ha="left", y=0.985, fontsize=20, fontweight="bold")
    runs_label = "runs" if all(run["attempted"] for run in data["trajectories"]) else "planned runs"
    fig.text(0.065, 0.932, f"{counts['accepted']} accepted / {counts['recorded_attempts']} attempted encounters · {len(seeds)} {runs_label} per pair · feelings clipped to [−1, +1]", color=MUTED, fontsize=10.5)
    controls = {c["case"]: c["points"] for c in data["mechanical_controls"]}
    for row, (case, names) in enumerate(CASE_NAMES.items()):
        for col, seed in enumerate(seeds):
            ax = axes[row, col]
            run = next(run for run in data["trajectories"] if run["case"] == case and run["seed"] == seed)
            times = np.array([point["time"] for point in controls[case]])
            dense_t = np.linspace(0, steps * h, 220)
            class_paths = continuous(case, design["initial_affection"], dense_t)
            accepted = [item for item in run["encounters"] if item.get("accepted") is True]
            actual_t = [0] + [item["time"] for item in accepted]
            actual = np.array([design["initial_affection"]] + [item["affection_after"] for item in accepted])
            for i, (name, color) in enumerate(zip(names, COLORS)):
                ax.plot(dense_t, class_paths[i], color=color, linestyle="--", linewidth=1.2, alpha=0.55)
                ax.plot(times, [p["held_partner_oracle"][i] for p in controls[case]], color=color, linestyle=":", linewidth=1.8, alpha=0.8)
                ax.plot(times, [p["self_only"][i] for p in controls[case]], color=color, linestyle="-.", linewidth=1, alpha=0.35)
                ax.plot(actual_t, actual[:, i], color=color, marker="o", markersize=4.5, linewidth=2.5, label=name, zorder=5)
                clipped = [item for item in accepted if next(u for u in item["updates"] if u["character"] == name)["clipped"]]
                if clipped:
                    ax.scatter([item["time"] for item in clipped], [item["affection_after"][i] for item in clipped],
                               marker="s", s=49, facecolors="white", edgecolors=color, linewidths=1.5, zorder=6)
            failures = Counter(item["time"] for item in run["encounters"] if item.get("accepted") is False)
            for t, number in failures.items():
                ax.scatter([t], [-1.17], marker="x", s=45, color=RED, linewidths=1.5, zorder=8)
                if number > 1:
                    ax.annotate(str(number), (t, -1.17), xytext=(6, 1), textcoords="offset points", color=RED, fontsize=9)
            for item in run["encounters"]:
                if item.get("accepted") is None:
                    ax.annotate("?", (item["last_known_time"], -1.17), color=RED, fontweight="bold", ha="center")
            for boundary in [-1, 1]:
                ax.axhline(boundary, color="#D2DBDF", linewidth=0.9, zorder=0)
            ax.axhline(0, color="#E2E8EB", linewidth=0.8, zorder=0)
            ax.set_ylim(-1.26, 1.1)
            ax.set_xlim(-0.06, steps * h + 0.06)
            ax.set_yticks([-1, -0.5, 0, 0.5, 1])
            ax.set_xticks(np.arange(steps + 1) * h)
            ax.grid(axis="x", color="#F1F4F5", linewidth=0.7)
            state = f"{run['accepted']}/{run['attempted']} accepted" if run["attempted"] else "not run"
            ax.set_title(f"{'–'.join(names)} · seed {seed}\n{state}", loc="left", pad=10)
            ax.legend(frameon=False, fontsize=9, loc="upper right" if row == 0 else "lower left", ncol=2, handlelength=1.8)
            if col == 0:
                ax.set_ylabel("Research affection")
            if row == 1:
                ax.set_xlabel("Model time = accepted updates × 0.5")
    handles = [Line2D([], [], color=INK, marker="o", linewidth=2, label="Generated conversation feedback"),
               Line2D([], [], color=MUTED, linestyle="--", label="Continuous class equations"),
               Line2D([], [], color=MUTED, linestyle=":", label="Held partner-state oracle"),
               Line2D([], [], color=MUTED, linestyle="-.", label="Self-only mechanical control")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.06, 0.904), frameon=False, ncol=2, columnspacing=2.2, fontsize=9)
    rug_note = "Red × below an axis: rejected attempt; its model clock did not advance. Squares: a clipped update."
    if counts["incomplete_records"]:
        rug_note += " ? = incomplete record."
    fig.text(0.065, 0.082, rug_note, color=MUTED, fontsize=9)
    fig.text(0.065, 0.048, "Dashed/dotted controls contain no dialogue. A full class-model cycle lasts 2π ≈ 6.28; even five accepted updates cover only 2.5.", color=MUTED, fontsize=9)
    save_figure(fig, "06-fable-feedback")


def reactions_plot(data):
    seeds = data["design"]["seeds"]
    slots = []
    for run in data["trajectories"]:
        by_attempt = {item["attempt"]: item for item in run["encounters"]}
        for attempt in range(1, run["planned_attempts"] + 1):
            item = by_attempt.get(attempt)
            prefix = "R/J" if run["case"] == "romeo-juliet" else "S/G"
            label = f"{prefix} S{seeds.index(run['seed']) + 1} · {attempt}"
            slots.append((run, item, label))
    keys = list(INTENT_LABELS)
    matrix = np.full((len(slots), len(keys)), np.nan)
    for index, (_, item, _) in enumerate(slots):
        if item and item.get("rating"):
            matrix[index] = [item["rating"]["probabilities"][key] for key in keys]
    fig = plt.figure(figsize=(13.6, 10.0))
    grid = fig.add_gridspec(2, 2, left=0.12, right=0.97, top=0.86, bottom=0.2,
                          width_ratios=[1.36, 1], hspace=0.47, wspace=0.3)
    heat = fig.add_subplot(grid[:, 0])
    fig.suptitle("Selected reactions and affection updates", x=0.055, ha="left", y=0.985, fontsize=19, fontweight="bold")
    fig.text(0.055, 0.938, "Saved Jev reaction weights and Scout's utterance-grounded warmth ratings · descriptive pilot, no population inference", color=MUTED, fontsize=10.5)
    cmap = plt.get_cmap("Blues").copy()
    cmap.set_bad("#EBEEF0")
    image = heat.imshow(matrix, cmap=cmap, vmin=0, vmax=1, aspect="auto", interpolation="none")
    heat.set_title("Jev selection probabilities (%)", loc="left", pad=11, fontweight="bold")
    heat.set_xticks(range(len(keys)), list(INTENT_LABELS.values()), rotation=42, ha="right", fontsize=8)
    heat.set_yticks(range(len(slots)), [label for _, _, label in slots], fontsize=8)
    for index, (_, item, _) in enumerate(slots):
        if item and item.get("accepted") is False:
            heat.get_yticklabels()[index].set_color(RED)
            heat.text(7.58, index, "×", color=RED, fontsize=10, va="center")
        if not item:
            heat.text(3.5, index, "not attempted", color=MUTED, fontsize=8, ha="center", va="center")
        elif not item.get("rating"):
            label = "incomplete record" if item.get("accepted") is None else "no valid rating vector"
            heat.text(3.5, index, label, color=MUTED, fontsize=8, ha="center", va="center")
        else:
            for j, probability in enumerate(matrix[index]):
                label = "<1" if 0 < probability < 0.01 else str(round(100 * probability))
                heat.text(j, index, label, ha="center", va="center", fontsize=7.5,
                          color="white" if probability > 0.55 else INK)
            selection = item.get("selected_intent")
            if selection:
                heat.add_patch(Rectangle((keys.index(selection) - 0.46, index - 0.46), 0.92, 0.92,
                                         fill=False, edgecolor="#CE8432", linewidth=2.2))
    group_size = data["design"]["attempts_per_run"]
    for boundary in range(group_size, len(slots), group_size):
        heat.axhline(boundary - 0.5, color="white", linewidth=2.8)
    for spine in heat.spines.values():
        spine.set_visible(False)
    heat.set_ylim(len(slots) - 0.5, -0.5)
    for case_index, (case, names) in enumerate(CASE_NAMES.items()):
        ax = fig.add_subplot(grid[case_index, 1])
        updates = [u for run in data["trajectories"] if run["case"] == case for row in run["encounters"]
                   if row.get("accepted") is True for u in row["updates"]]
        for i, name in enumerate(names):
            counts = Counter((u["warmth"], round(u["change"], 12), u["clipped"]) for u in updates if u["character"] == name)
            for (warmth, change, clipped), number in counts.items():
                ax.scatter(warmth, change, marker="s" if clipped else "o", s=55,
                           facecolors="white" if clipped else COLORS[i], edgecolors=COLORS[i], linewidth=1.7, zorder=4)
                if number > 1:
                    # Move the clipped point's label left; keep all data coordinates exact.
                    label_left = clipped and change > 0
                    offset = (-8, 0) if label_left else (7, 5 if i == 0 else -12)
                    ax.annotate(f"×{number}", (warmth, change), xytext=offset,
                                ha="right" if label_left else "left",
                                textcoords="offset points", fontsize=8, color=COLORS[i])
        ax.axhline(0, color="#CDD7DC", linewidth=0.8)
        ax.axvline(0, color="#E3E9EC", linewidth=0.8)
        ax.set_xlim(-1.16, 1.16)
        maximum = max([abs(u["change"]) for u in updates] + [0.3])
        ax.set_ylim(-maximum * 1.35, maximum * 1.35)
        ax.set_xticks([-1, -0.5, 0, 0.5, 1])
        ax.set_title(f"{'–'.join(names)} · {len(updates)} accepted person-updates", loc="left", fontsize=10.5, fontweight="bold")
        ax.set_xlabel("Partner's expressed warmth (automated rating)", fontsize=9)
        ax.set_ylabel("Change in research affection", fontsize=9)
        ax.legend(handles=[Line2D([], [], color=COLORS[i], marker="o", linestyle="none", label=name) for i, name in enumerate(names)],
                  frameon=False, fontsize=8, loc="upper left", ncol=2)
        if not updates:
            ax.text(0.5, 0.55, "No accepted updates", transform=ax.transAxes, ha="center", color=MUTED)
    # Explicit normalized scale; this is not an inferred frequency histogram.
    cb = fig.colorbar(image, ax=heat, orientation="horizontal", fraction=0.026, pad=0.21, ticks=[0, 0.5, 1])
    cb.ax.set_xticklabels(["0%", "50%", "100%"])
    cb.ax.tick_params(labelsize=8)
    cb.outline.set_visible(False)
    fig.text(0.055, 0.115, f"Gold box = sampled intention for the focal speaker. Red row = rejected encounter. S1 = {seeds[0]}; S2 = {seeds[1]}.", color=MUTED, fontsize=9)
    fig.text(0.055, 0.078, "Right: every accepted person's update; ×n marks coincident points. Hollow squares hit a clipping bound. No regression or confidence interval.", color=MUTED, fontsize=9)
    fig.text(0.055, 0.041, "Warmth is an uncalibrated expression rating. A negative response coefficient can turn perceived warmth into declining affection.", color=MUTED, fontsize=9)
    save_figure(fig, "07-fable-reactions")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--input", type=Path, help="Private completed run directory")
    sources.add_argument("--from-export", type=Path, help="Redraw exclusively from the public whitelist JSON")
    parser.add_argument("--provider-finished", action="store_true", help="Confirm the provider process and pending requests have ended")
    args = parser.parse_args()
    if args.input:
        if not args.provider_finished:
            parser.error("Wait for provider completion, then pass --provider-finished")
        data = extract(args.input)
        output = ROOT / "fable-pilot-results.json"
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    else:
        data = read(args.from_export)
        if data.get("format_version") != 1 or data.get("design", {}).get("models") != MODELS:
            raise ValueError("Unexpected export format")
    style()
    feedback_plot(data)
    reactions_plot(data)
    print(json.dumps({"counts": data["counts"], "accounting": data["accounting"],
                      "data_flow_verification": data["data_flow_verification"]}, indent=2))


if __name__ == "__main__":
    main()
