# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["numpy==2.2.6", "scipy==1.15.3", "matplotlib==3.10.3"]
# ///
"""Draw the concise article's overlays from equations and frozen public pilot data.

    uv run illustrate-dynamics.py

No provider calls or private application files. The noise experiment has 8,000
trajectories in paired conditions, plus two noise-free numerical controls.
Influenced by PHYS 4410 Nonlinear Dynamics.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np
import scipy
from scipy.integrate import quad_vec
from scipy.linalg import expm


ROOT = Path(__file__).resolve().parent
SEED, N, STEPS = 20260928, 2_000, 1_000
T = 2 * np.pi
H = T / STEPS
SIGMAS = (0.05, 0.15)
EXAMPLE_IDS = (0, 1, 2)  # Fixed before simulating; no selection by appearance.
INITIAL = np.array([1.0, 0.0])
TIMES = np.linspace(0, T, STEPS + 1)
INK, GRAY, PALE = "#25313D", "#68757C", "#E2E7E9"
MEAN = "#922F8E"
PATH_COLORS = ("#128B94", "#DD793E", "#639842")
RUN_COLORS = ("#127D8C", "#CB6943")
CASES = (
    {"id": "romeo-juliet", "title": "Romeo & Juliet", "names": ("Romeo", "Juliet"),
     "matrix": [[0.0, 1.0], [-1.0, 0.0]], "ideal_mutual_share": 0.25},
    {"id": "susan-george", "title": "Susan & George", "names": ("Susan", "George"),
     "matrix": [[1.0, 2.0], [-1.0, -1.0]], "ideal_mutual_share": 0.125},
)


def setup_style():
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 11, "axes.titlesize": 12,
        "axes.labelsize": 11, "axes.labelcolor": INK, "text.color": INK,
        "xtick.color": GRAY, "ytick.color": GRAY, "axes.edgecolor": "#C5CDD2",
        "axes.spines.top": False, "axes.spines.right": False,
        "savefig.facecolor": "#FFFFFF", "figure.facecolor": "#FFFFFF",
        "svg.fonttype": "none", "svg.hashsalt": "fable-love-article-20260928",
    })


def transition(A, h):
    """Exact transition for unit isotropic diffusion; scale shocks by sigma."""
    block = np.block([[A, np.eye(2)], [np.zeros((2, 2)), -A.T]])
    E = expm(block * h)
    F = E[:2, :2]
    Q = E[:2, 2:] @ F.T
    Q = (Q + Q.T) / 2
    return F, Q, np.linalg.cholesky(Q)


def analytic(A, times):
    # Both matrices satisfy A^2 = -I, so exp(At) = I cos(t) + A sin(t).
    np.testing.assert_allclose(A @ A, -np.eye(2), atol=1e-14)
    t = np.asarray(times)
    return np.cos(t)[:, None] * INITIAL + np.sin(t)[:, None] * (A @ INITIAL)


def simulate(case, index):
    A = np.asarray(case["matrix"])
    F, Q, L = transition(A, H)
    exact = analytic(A, TIMES)
    numerical = np.empty_like(exact)
    numerical[0] = INITIAL
    for k in range(STEPS):
        numerical[k + 1] = F @ numerical[k]
    error = float(np.max(np.abs(numerical - exact)))
    assert error < 2e-12

    # Midpoints avoid the zero-crossing ambiguity of a strictly positive test.
    fine_times = (np.arange(20_000) + 0.5) * T / 20_000
    fine = analytic(A, fine_times)
    ideal_share = float(np.mean(np.all(fine > 0, axis=1)))
    assert abs(ideal_share - case["ideal_mutual_share"]) < 1e-12
    numerical_midpoints = np.einsum("ij,kj->ik", numerical[:-1], expm(A * H / 2), optimize=False)
    numerical_share = float(np.mean(np.all(numerical_midpoints > 0, axis=1)))
    assert abs(numerical_share - ideal_share) < 1e-12

    F2, Q2, _ = transition(A, 2 * H)
    np.testing.assert_allclose(F2, F @ F, atol=1e-14)
    np.testing.assert_allclose(Q2, F @ Q @ F.T + Q, atol=1e-14)
    covariance_quad, _ = quad_vec(lambda s: expm(A * s) @ expm(A.T * s), 0, T,
                                  epsabs=1e-11, epsrel=1e-11)
    covariance_closed = np.pi * (np.eye(2) + A @ A.T)
    np.testing.assert_allclose(covariance_quad, covariance_closed, rtol=2e-12, atol=2e-12)

    rng = np.random.default_rng(np.random.SeedSequence([SEED, index]))
    perturbations = np.zeros((N, 2))
    means = {sigma: np.empty((STEPS + 1, 2)) for sigma in SIGMAS}
    examples = {sigma: np.empty((STEPS + 1, len(EXAMPLE_IDS), 2)) for sigma in SIGMAS}
    counts = {sigma: np.zeros(N, dtype=np.int32) for sigma in SIGMAS}
    coarse_counts = {sigma: np.zeros(N, dtype=np.int32) for sigma in SIGMAS}
    covariance = np.zeros((2, 2))
    for k in range(STEPS + 1):
        # One shared unit-noise process pairs each run between noise amplitudes.
        for sigma in SIGMAS:
            X = numerical[k] + sigma * perturbations
            means[sigma][k] = X.mean(axis=0)
            examples[sigma][k] = X[list(EXAMPLE_IDS)]
            if k < STEPS:
                mutual = np.all(X > 0, axis=1)
                counts[sigma] += mutual
                if k % 2 == 0:
                    coarse_counts[sigma] += mutual
        if k < STEPS:
            z = rng.standard_normal((N, 2))
            perturbations = (np.einsum("ij,kj->ik", perturbations, F, optimize=False)
                             + np.einsum("ij,kj->ik", z, L, optimize=False))
            covariance = F @ covariance @ F.T + Q
    np.testing.assert_allclose(covariance, covariance_closed, rtol=2e-11, atol=2e-11)

    conditions = []
    for sigma in SIGMAS:
        X = numerical[-1] + sigma * perturbations
        fractions = counts[sigma] / STEPS
        coarse = coarse_counts[sigma] / (STEPS // 2)
        target_cov = sigma**2 * covariance_closed
        empirical_cov = np.cov(X, rowvar=False)
        endpoint_error_se = (X.mean(axis=0) - exact[-1]) / np.sqrt(np.diag(target_cov) / N)
        covariance_se = np.sqrt((target_cov**2 + np.outer(np.diag(target_cov), np.diag(target_cov))) / (N - 1))
        covariance_error_se = (empirical_cov - target_cov) / covariance_se
        assert np.max(np.abs(endpoint_error_se)) < 6
        assert np.max(np.abs(covariance_error_se)) < 6
        conditions.append({
            "sigma": sigma, "n": N,
            "time_share_mean": float(fractions.mean()),
            "time_share_sd_across_runs": float(fractions.std(ddof=1)),
            "time_share_middle_95_percent": np.quantile(fractions, [0.025, 0.975]).tolist(),
            "time_share_median": float(np.median(fractions)),
            "time_share_mean_coarsening_difference": float(coarse.mean() - fractions.mean()),
            "maximum_mean_curve_coordinate_error": float(np.max(np.abs(means[sigma] - exact))),
            "rms_mean_curve_coordinate_error": float(np.sqrt(np.mean((means[sigma] - exact)**2))),
            "endpoint_empirical_mean": X.mean(axis=0).tolist(),
            "endpoint_theoretical_mean": exact[-1].tolist(),
            "endpoint_empirical_covariance": empirical_cov.tolist(),
            "endpoint_theoretical_covariance": target_cov.tolist(),
            "endpoint_mean_error_in_mc_standard_errors": endpoint_error_se.tolist(),
            "endpoint_covariance_error_in_mc_standard_errors": covariance_error_se.tolist(),
        })

    summary = {
        "case": case["id"], "matrix": A.tolist(),
        "ideal_mutual_affection_time_share": ideal_share,
        "noise_free_numerical_mutual_affection_time_share": numerical_share,
        "noise_free_max_coordinate_error": error,
        "noise_free_return_error": float(np.linalg.norm(numerical[-1] - INITIAL)),
        "conditions": conditions,
    }
    return {"case": case, "exact": exact, "numerical": numerical,
            "means": means, "examples": examples}, summary


def save_figure(fig, directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "svg"):
        metadata = {"Creator": "illustrate-dynamics.py"} if extension == "svg" else None
        fig.savefig(directory / f"{name}.{extension}", dpi=210, bbox_inches="tight", metadata=metadata)
    plt.close(fig)


def noise_overlay(data, directory):
    fig, axes = plt.subplots(2, 3, figsize=(12.6, 9.65))
    fig.subplots_adjust(left=0.07, right=0.985, top=0.77, bottom=0.14, wspace=0.25, hspace=0.44)
    fig.text(0.07, 0.98, "Same rules. Different days.", fontsize=22, weight="bold", va="top")
    fig.text(0.07, 0.92, "Two ideal cycles, with a little everyday randomness added.", fontsize=13, color=GRAY)
    handles = [Line2D([0], [0], color=INK, lw=2.3, label="Ideal mathematical orbit"),
               Line2D([0], [0], color=MEAN, lw=2, linestyle="--", label="Average of 2,000 noisy runs"),
               Line2D([0], [0], color=PATH_COLORS[0], lw=1.8, label="Three individual runs (three colors)"),
               Line2D([0], [0], color=MEAN, marker="o", markersize=4, lw=0, label="Noise-free numerical check")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.062, 0.892), frameon=False,
               ncol=2, fontsize=10.5, columnspacing=2.2, handlelength=3)
    titles = ("No noise  ·  $\\sigma=0$", "Small surprises  ·  $\\sigma=0.05$", "Bigger surprises  ·  $\\sigma=0.15$")
    for row, record in enumerate(data):
        case, exact = record["case"], record["exact"]
        A = np.asarray(case["matrix"])
        # All three columns in a row have exactly the same scale. No sample is clipped.
        points = np.concatenate([exact] + [a.reshape(-1, 2) for a in record["examples"].values()]
                                + list(record["means"].values()))
        radius = math.ceil((float(np.abs(points).max()) + 0.13) * 4) / 4
        positions = np.linspace(-radius, radius, 15)
        xx, yy = np.meshgrid(positions, positions)
        arrows = np.einsum("ij,kj->ik", np.column_stack([xx.ravel(), yy.ravel()]), A, optimize=False)
        norm = np.linalg.norm(arrows, axis=1)
        arrows = np.divide(arrows, norm[:, None], out=np.zeros_like(arrows), where=norm[:, None] > 0)
        for col, sigma in enumerate((0.0, *SIGMAS)):
            ax = axes[row, col]
            ax.set_xlim(-radius, radius)
            ax.set_ylim(-radius, radius)
            ax.set_aspect("equal")
            ax.add_patch(Rectangle((0, 0), radius, radius, facecolor="#F8F2D8", edgecolor="none", zorder=0))
            ax.quiver(xx, yy, arrows[:, 0].reshape(xx.shape), arrows[:, 1].reshape(xx.shape),
                      color="#CBD2D5", angles="xy", scale_units="xy", scale=7.0 / radius,
                      width=0.0033, headwidth=3.2, zorder=1)
            ax.axhline(0, color="#BFC8CD", lw=0.8, zorder=1)
            ax.axvline(0, color="#BFC8CD", lw=0.8, zorder=1)
            if sigma:
                for j, color in enumerate(PATH_COLORS):
                    path = record["examples"][sigma][:, j]
                    ax.plot(*path.T, color=color, lw=1.2, alpha=0.78, zorder=3)
                    ax.scatter(*path[-1], color=color, s=20, zorder=5, edgecolors="white", linewidths=0.5)
            ax.plot(*exact.T, color=INK, lw=2.1, zorder=4)
            if sigma:
                ax.plot(*record["means"][sigma].T, color=MEAN, lw=1.65, linestyle=(0, (4, 3)), zorder=6)
            else:
                ax.plot(*record["numerical"][::40].T, lw=0, marker="o", markersize=3.2,
                        markerfacecolor="white", markeredgewidth=1.1, color=MEAN, zorder=6)
            ax.scatter(*INITIAL, s=31, color=INK, edgecolors="white", linewidth=0.7, zorder=7)
            ax.set_xticks([-1, 0, 1] if radius < 2 else [-2, 0, 2])
            ax.set_yticks([-1, 0, 1] if radius < 2 else [-2, 0, 2])
            ax.set_xlabel(f"{case['names'][0]}'s feeling")
            ax.set_ylabel(f"{case['names'][1]}'s feeling" if col == 0 else "")
            ax.set_title((case["title"] if col == 0 else "") + "\n" + titles[col], pad=11, weight="bold")
    fig.text(0.07, 0.046, "Gray arrows = direction of the ideal rules. Gold quadrant = both feelings positive.",
             fontsize=10.5, color=GRAY)
    fig.text(0.07, 0.020, "All runs start together at (1, 0); one period, 1,000 intervals. Noise levels share the same shocks.",
             fontsize=10.5, color=GRAY)
    save_figure(fig, directory, "08-noise-overlay")


def held_response(r, u, a, b, h):
    phi = h if a == 0 else math.expm1(a * h) / a
    return float(np.clip(math.exp(a * h) * r + b * phi * u, -1, 1))


def conversation_dynamics(pilot, directory):
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 6.25))
    fig.subplots_adjust(left=0.085, right=0.98, top=0.66, bottom=0.29, wspace=0.29)
    fig.text(0.085, 0.975, "The rules made it into the conversation loop.", fontsize=20, weight="bold", va="top")
    fig.text(0.085, 0.90, "Real generated conversations; two short runs per couple.", fontsize=12.5, color=GRAY)
    handles = [Line2D([0], [0], color=INK, lw=1.7, linestyle="--", label="What the rule says"),
               Line2D([0], [0], color=RUN_COLORS[0], marker="o", markerfacecolor="white", markersize=7,
                      lw=0, label="Saved Fable feeling · run 1"),
               Line2D([0], [0], color=RUN_COLORS[1], marker="x", markersize=7, lw=0, label="Saved Fable feeling · run 2")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.075, 0.865), frameon=False,
               ncol=3, fontsize=10.5, handlelength=2.6, columnspacing=1.3)
    h = pilot["design"]["step_duration"]
    checks = []
    for panel, (case_id, character, index, a, b) in enumerate([
        ("susan-george", "Susan", 0, 1, 2),
        ("romeo-juliet", "Juliet", 1, 0, -1),
    ]):
        ax = axes[panel]
        paths = [p for p in pilot["trajectories"] if p["case"] == case_id]
        for run, trajectory in enumerate(paths):
            accepted = [e for e in trajectory["encounters"] if e["accepted"]]
            values = [trajectory["initial_affection"][index]] + [e["affection_after"][index] for e in accepted]
            prediction = [values[0]]
            warmth = []
            for e in accepted:
                u = next(o["warmth"] for o in e["observations"] if o["listener"] == character)
                warmth.append(u)
                prediction.append(held_response(prediction[-1], u, a, b, h))
            np.testing.assert_allclose(prediction, values, atol=2e-12, rtol=2e-12)
            if character == "Susan":
                assert all(u == 0 for u in warmth)
                closed = np.minimum(1, 0.2 * np.exp(np.arange(len(values)) * h))
                np.testing.assert_allclose(values, closed, atol=2e-12, rtol=2e-12)
            x = np.arange(len(values))
            ax.plot(x, prediction, color=INK, linestyle="--", lw=1.7, zorder=2)
            ax.plot(x, values, lw=0, marker="o" if run == 0 else "x", markersize=8 if run == 0 else 6.5,
                    markerfacecolor="white", markeredgewidth=1.9, color=RUN_COLORS[run], zorder=4 + run)
            checks.append({"case": case_id, "character": character, "seed": trajectory["seed"],
                           "accepted_steps": len(accepted), "observed_warmth": warmth,
                           "saved_affection": values, "replayed_affection": prediction,
                           "maximum_replay_error": float(np.max(np.abs(np.array(values) - prediction)))})
        ax.set_xticks(range(6))
        ax.set_xlim(-0.12, 5.13)
        ax.set_xlabel("Accepted conversation")
        ax.set_ylabel("Research affection")
        ax.grid(axis="y", color=PALE, lw=0.7, zorder=0)
        if panel == 0:
            ax.set_ylim(-0.08, 1.12)
            ax.set_yticks([0, 0.5, 1])
            ax.set_title("Susan: a crush feeds itself\n$s_k=\\min(1,\\,0.2e^{0.5k})$", weight="bold", pad=12)
            ax.axhline(1, color=GRAY, lw=0.8, alpha=0.6)
            ax.annotate("Both runs overlap", (2, values[2]), xytext=(0.9, 0.9),
                        arrowprops={"arrowstyle": "-", "color": GRAY, "lw": 0.8}, fontsize=10, color=GRAY)
        else:
            ax.set_ylim(-1.12, 0.12)
            ax.set_yticks([-1, -0.5, 0])
            ax.set_title("Juliet: warmth makes her retreat\n$j_{k+1}=\\max(-1,\\,j_k-0.5u_k)$", weight="bold", pad=12)
            ax.axhline(-1, color=GRAY, lw=0.8, alpha=0.6)
    fig.text(0.085, 0.135, "Here, $u$ is the appraiser's warmth rating of Romeo's speech; George's rated warmth stayed at 0.",
             fontsize=10.5, color=GRAY)
    fig.text(0.085, 0.090, "Affection is capped at ±1. One rejected Romeo–Juliet attempt did not advance the state or clock.",
             fontsize=10.5, color=GRAY)
    fig.text(0.085, 0.045, "This checks the authored updates after dialogue. These short runs did not reproduce a full mathematical cycle.",
             fontsize=10.5, color=INK)
    save_figure(fig, directory, "09-conversation-dynamics")
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--pilot", type=Path, default=ROOT / "fable-pilot-results.json")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    setup_style()
    figures = args.output / "figures"
    data, summaries = [], []
    for index, case in enumerate(CASES):
        arrays, summary = simulate(case, index)
        data.append(arrays)
        summaries.append(summary)
    noise_overlay(data, figures)
    pilot = json.loads(args.pilot.read_text())
    checks = conversation_dynamics(pilot, figures)
    result = {
        "experiment": "Article phase-space overlays; independent of the earlier 80,000-trajectory baseline.",
        "protocol": {
            "seed": SEED, "generator": "NumPy PCG64; SeedSequence([seed, case_index])",
            "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
            "matplotlib": matplotlib.__version__, "initial_state": INITIAL.tolist(), "initial_spread": 0,
            "duration": T, "intervals": STEPS, "step_duration": H, "sigmas": [0, *SIGMAS],
            "noisy_runs_per_case_per_nonzero_sigma": N, "total_noisy_trajectories": N * 2 * 2,
            "independent_shock_streams": N * 2, "noise_free_numerical_controls": 2,
            "paired_innovations_between_amplitudes": True,
            "noise_definition": "dX = A X dt + sigma dW, with independent standard Brownian components.",
            "noise_scale": "External driving increments have SD sigma*sqrt(dt). Exact state increments include drift during the interval.",
            "transition": "Exact matrix exponential and integrated Gaussian covariance (Van Loan block exponential).",
            "time_share_estimator": "1,000 left endpoints excluding final T; strict positivity in both coordinates; numerical residence estimate.",
            "time_share_spread": "Empirical 2.5th and 97.5th percentiles across runs, not confidence intervals for the mean.",
            "ideal_time_share_check": "20,000 analytic midpoints; also 1,000 exact-update numerical midpoints.",
            "example_ids": list(EXAMPLE_IDS), "example_selection": "First three paths fixed before simulation, not selected by outcome.",
            "plot_scales": "Equal aspect; same symmetric coordinate bounds across noise levels within each couple; no shown path clipped.",
            "vector_field": "Normalized deterministic drift direction, not speed and not a stochastic sample-path derivative.",
            "theoretical_mean": "E[X(t)] = exp(A*t)*X(0) for all displayed noise levels; finite-sample means need not coincide exactly.",
            "no_clipping": True,
        },
        "mathematical_cases": summaries,
        "verification": {
            "exact_transition_composition": "passed",
            "covariance_quadrature_and_full_period_closed_form": "passed",
            "monte_carlo_mean_and_covariance_within_six_standard_errors": "passed",
            "conversation_replay": "passed",
        },
        "conversation_figure": {
            "source": "fable-pilot-results.json", "new_provider_calls": 0,
            "pilot_counts": pilot["counts"], "checks": checks,
            "interpretation": "Replays the authored response rule with rated speech. Not an independent behavioral prediction or evidence of full-cycle reproduction.",
        },
    }
    (args.output / "article-dynamics-results.json").write_text(json.dumps(result, indent=2) + "\n")
    for summary in summaries:
        print(summary["case"], "noise-free share:", summary["ideal_mutual_affection_time_share"])
        for condition in summary["conditions"]:
            print("  sigma", condition["sigma"], "mean share", condition["time_share_mean"],
                  "middle 95%", condition["time_share_middle_95_percent"])
    print("Wrote article-dynamics-results.json and figures 08–09 (PNG + SVG).")


if __name__ == "__main__":
    main()
