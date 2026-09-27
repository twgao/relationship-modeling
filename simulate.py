# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#   "numpy==2.2.6",
#   "scipy==1.15.3",
#   "matplotlib==3.10.3",
# ]
# ///
"""Reproduce the relationship figures and numerical results.

Run from any directory: uv run /path/to/simulate.py
No input PDFs, credentials, application services, or repository packages are needed.
Influenced by PHYS 4410 Nonlinear Dynamics. The random variations are chosen
extensions of deterministic relationship models, not fitted relationship data.
"""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import scipy
from scipy.integrate import quad, quad_vec, solve_ivp
from scipy.linalg import expm
from scipy.stats import norm

SEED = 20260927
N = 10_000
T = 4 * np.pi
STEPS = 1_000
H = T / STEPS
INITIAL_SD = 0.20
NOISE_SD = 0.15
PARAMETER_SD = 0.05
TIMES = np.linspace(0, T, STEPS + 1)
FIRST = "#3268a8"
SECOND = "#c05b35"
INK = "#243448"
PALE = "#d8e5f1"

CORE = {
    "romeo_juliet": {
        "title": "Romeo and Juliet",
        "A": np.array([[0.0, 1.0], [-1.0, 0.0]]),
        "mean0": np.array([1.0, 0.0]),
        "first": "Romeo",
        "second": "Juliet",
    },
    "george_susan": {
        "title": "Susan and George",
        "A": np.array([[1.0, 2.0], [-1.0, -1.0]]),
        "mean0": np.array([1.0, 0.0]),
        "first": "Susan",
        "second": "George",
    },
    "cautious_fading": {
        "title": "Caution dominates",
        "A": np.array([[-1.0, 0.5], [0.5, -1.0]]),
        "mean0": np.array([1.0, 0.0]),
        "first": "Romeo",
        "second": "Juliet",
    },
    "cautious_growing": {
        "title": "Responsiveness dominates",
        "A": np.array([[-0.5, 1.0], [1.0, -0.5]]),
        "mean0": np.array([0.2, -0.1]),
        "first": "Romeo",
        "second": "Juliet",
    },
}

OTHER_CASES = {
    "eager_and_cautious": np.array([[1.0, 1.0], [1.0, -1.0]]),
    "cautious_boundary": np.array([[-1.0, 1.0], [1.0, -1.0]]),
    "exercise_5_3_2": np.array([[0.0, 1.0], [-1.0, 1.0]]),
    "out_of_touch": np.array([[0.0, 1.0], [1.0, 0.0]]),
    "fire_and_water": np.array([[0.5, 1.0], [-1.0, -0.5]]),
    "peas_in_a_pod": np.array([[1.0, -0.5], [-0.5, 1.0]]),
    "romeo_robot": np.array([[0.0, 0.0], [1.0, -1.0]]),
}


def exact_path(A: np.ndarray, x0: np.ndarray, times: np.ndarray) -> np.ndarray:
    return np.array([expm(A * t) @ x0 for t in times])


def transition(A: np.ndarray, h: float, sigma: float):
    """Exact linear-Gaussian transition, via a 4x4 block exponential.

    exp([[A, D], [0, -A.T]] h) = [[F, G], [0, F**(-T)]],
    with D = sigma**2 I and Q = G F.T. For a sampled time interval,
    X_next = F X + eta, eta ~ N(0, Q). No Euler drift is introduced.
    """
    if sigma == 0:
        return expm(A * h), np.zeros((2, 2)), np.zeros((2, 2))
    M = np.block([[A, sigma**2 * np.eye(2)], [np.zeros((2, 2)), -A.T]])
    E = expm(M * h)
    F = E[:2, :2]
    Q = E[:2, 2:] @ F.T
    Q = (Q + Q.T) / 2
    return F, Q, np.linalg.cholesky(Q)


def moments_by_quadrature(A: np.ndarray, mean0: np.ndarray, sigma: float, t: float):
    """Independent continuous-time check, not the transition recurrence."""
    F = expm(A * t)
    covariance = INITIAL_SD**2 * F @ F.T
    if sigma:
        integral, _ = quad_vec(lambda s: expm(A * s) @ expm(A.T * s), 0, t,
                               epsabs=1e-11, epsrel=1e-11)
        covariance += sigma**2 * integral
    return F @ mean0, covariance


def positive_quadrant_probability(mean: np.ndarray, covariance: np.ndarray) -> float:
    sd = np.sqrt(np.diag(covariance))
    rho = np.clip(covariance[0, 1] / np.prod(sd), -1 + 1e-14, 1 - 1e-14)
    lower = -mean[0] / sd[0]
    result, _ = quad(
        lambda z: norm.pdf(z) * norm.cdf(
            (mean[1] / sd[1] + rho * z) / np.sqrt(1 - rho**2)),
        lower, np.inf, epsabs=1e-9, epsrel=1e-9,
    )
    return float(result)


def wilson_interval(successes: int, count: int) -> list[float]:
    z = norm.ppf(0.975)
    p = successes / count
    denominator = 1 + z**2 / count
    center = (p + z**2 / (2 * count)) / denominator
    half = z * np.sqrt(p * (1 - p) / count + z**2 / (4 * count**2)) / denominator
    return [float(center - half), float(center + half)]


def classify(A: np.ndarray) -> str:
    tr = float(np.trace(A))
    det = float(np.linalg.det(A))
    disc = tr**2 - 4 * det
    if abs(det) < 1e-10:
        return "all_equilibria" if np.max(np.abs(A)) < 1e-10 else "line_of_equilibria"
    if det < 0:
        return "saddle"
    if disc < 0:
        if abs(tr) < 1e-10:
            return "center"
        return "stable_spiral" if tr < 0 else "unstable_spiral"
    return "stable_node" if tr < 0 else "unstable_node"


def simulate_case(key: str, index: int, sigma: float, initial: np.ndarray):
    case = CORE[key]
    A, mean0 = case["A"], case["mean0"]
    # Each case has its own stream. Arms share initial states for a paired comparison.
    rng = np.random.default_rng(np.random.SeedSequence([SEED, index, 1]))
    F, Q, L = transition(A, H, sigma)
    X = initial.copy()
    mean = mean0.copy()
    covariance = INITIAL_SD**2 * np.eye(2)
    empirical_means, empirical_variances, theoretical_means = [], [], []
    theoretical_variances, lower, upper, paths = [], [], [], []
    observed_times = []
    love_counts = np.zeros(N, dtype=np.int32)
    coarse_love_counts = np.zeros(N, dtype=np.int32)

    for step in range(STEPS + 1):
        if step % 10 == 0:
            observed_times.append(TIMES[step])
            empirical_means.append(X.mean(axis=0))
            empirical_variances.append(X.var(axis=0, ddof=1))
            theoretical_means.append(mean.copy())
            theoretical_variances.append(np.diag(covariance).copy())
            q = np.quantile(X, [0.025, 0.975], axis=0)
            lower.append(q[0])
            upper.append(q[1])
            paths.append(X[:8].copy())
        if step == STEPS:
            break
        # Residence estimates use the 1,000 left endpoints; T is not counted twice.
        loving = (X[:, 0] > 0) & (X[:, 1] > 0)
        love_counts += loving
        if step % 2 == 0:
            coarse_love_counts += loving
        # Explicit two-component contraction avoids spurious floating-point flags
        # from macOS Accelerate's tall-by-2 GEMM path. A minimal reproduction
        # returned finite, correct values while reporting divide/overflow/invalid.
        X = np.einsum("ij,kj->ik", X, F, optimize=False)
        if sigma:
            X += np.einsum("ij,kj->ik", rng.standard_normal((N, 2)), L, optimize=False)
        mean = F @ mean
        covariance = F @ covariance @ F.T + Q

    direct_mean, direct_cov = moments_by_quadrature(A, mean0, sigma, T)
    np.testing.assert_allclose(mean, direct_mean, rtol=2e-10, atol=1e-10)
    np.testing.assert_allclose(covariance, direct_cov, rtol=2e-9, atol=1e-11)
    sample_mean, sample_cov = X.mean(axis=0), np.cov(X, rowvar=False)
    mean_z = (sample_mean - direct_mean) / np.sqrt(np.diag(direct_cov) / N)
    cov_se = np.sqrt((direct_cov**2 + np.outer(np.diag(direct_cov), np.diag(direct_cov))) / (N - 1))
    covariance_z = (sample_cov - direct_cov) / cov_se
    assert np.max(np.abs(mean_z)) < 6, (key, sigma, "mean", mean_z)
    assert np.max(np.abs(covariance_z)) < 6, (key, sigma, "covariance", covariance_z)

    both_positive = int(np.sum((X[:, 0] > 0) & (X[:, 1] > 0)))
    both_negative = int(np.sum((X[:, 0] < 0) & (X[:, 1] < 0)))
    predicted_positive = positive_quadrant_probability(direct_mean, direct_cov)
    probability_se = np.sqrt(predicted_positive * (1 - predicted_positive) / N)
    assert abs(both_positive / N - predicted_positive) < max(6 * probability_se, 5 / N)
    fractions = love_counts / STEPS
    coarse_fractions = coarse_love_counts / (STEPS // 2)
    endpoint_quantiles = np.quantile(X, [0.025, 0.5, 0.975], axis=0)
    summary = {
        "n": N, "sigma": sigma, "initial_mean": mean0.tolist(),
        "initial_sd_each": INITIAL_SD,
        "theoretical_endpoint_mean": direct_mean.tolist(),
        "empirical_endpoint_mean": sample_mean.tolist(),
        "theoretical_endpoint_covariance": direct_cov.tolist(),
        "empirical_endpoint_covariance": sample_cov.tolist(),
        "endpoint_quantiles_025_50_975": endpoint_quantiles.tolist(),
        "mean_error_in_monte_carlo_se": mean_z.tolist(),
        "covariance_error_in_monte_carlo_se": covariance_z.tolist(),
        "both_positive_count": both_positive,
        "both_negative_count": both_negative,
        "mixed_sign_count": N - both_positive - both_negative,
        "predicted_both_positive_probability": predicted_positive,
        "both_positive_wilson_95": wilson_interval(both_positive, N),
        "mutual_love_time_fraction_mean": float(fractions.mean()),
        "mutual_love_time_fraction_sd": float(fractions.std(ddof=1)),
        "mutual_love_time_fraction_quantiles_025_50_975": np.quantile(fractions, [0.025, 0.5, 0.975]).tolist(),
        "coarsening_time_fraction_mean_change": float(coarse_fractions.mean() - fractions.mean()),
        "coarsening_time_fraction_mean_absolute_change": float(np.abs(coarse_fractions - fractions).mean()),
    }
    if key == "cautious_growing":
        common = np.exp(-0.5 * T) * X.sum(axis=1) / np.sqrt(2)
        common_mean = mean0.sum() / np.sqrt(2)
        common_variance = INITIAL_SD**2 + sigma**2 * (1 - np.exp(-T))
        common_count = int(np.sum(common > 0))
        summary["scaled_common_mode"] = {
            "theoretical_mean": float(common_mean),
            "theoretical_sd": float(np.sqrt(common_variance)),
            "empirical_mean": float(common.mean()),
            "empirical_sd": float(common.std(ddof=1)),
            "positive_count": common_count,
            "positive_wilson_95": wilson_interval(common_count, N),
            "predicted_positive_probability": float(norm.cdf(common_mean / np.sqrt(common_variance))),
        }
    arrays = {
        "times": np.array(observed_times), "means": np.array(empirical_means),
        "variances": np.array(empirical_variances), "exact_means": np.array(theoretical_means),
        "exact_variances": np.array(theoretical_variances),
        "lower": np.array(lower), "upper": np.array(upper), "paths": np.array(paths),
        "endpoints": X, "fractions": fractions,
    }
    return summary, arrays


def parameter_experiment():
    summaries = {}
    for index, (key, case) in enumerate(CORE.items()):
        rng = np.random.default_rng(np.random.SeedSequence([SEED, index, 2]))
        matrices = case["A"] + rng.normal(0, PARAMETER_SD, (N, 2, 2))
        labels, counts = np.unique([classify(A) for A in matrices], return_counts=True)
        summaries[key] = {
            "n": N, "coefficient_sd": PARAMETER_SD,
            "base_matrix": case["A"].tolist(),
            "counts": {str(label): int(count) for label, count in zip(labels, counts)},
        }
    return summaries


def deterministic_checks():
    cases = {key: value["A"] for key, value in CORE.items()} | OTHER_CASES
    checks = {}
    times = np.linspace(0, T, 501)
    for name, A in cases.items():
        x0 = np.array([1.0, 0.2])
        exact = exact_path(A, x0, times)
        numerical = solve_ivp(lambda t, x: A @ x, (0, T), x0, t_eval=times,
                              method="DOP853", rtol=1e-11, atol=1e-12)
        assert numerical.success
        relative_error = np.max(np.linalg.norm(numerical.y.T - exact, axis=1)
                                / np.maximum(1, np.linalg.norm(exact, axis=1)))
        assert relative_error < 2e-9, (name, relative_error)
        checks[name] = {"matrix": A.tolist(), "type": classify(A),
                        "independent_ode_max_relative_error": float(relative_error)}

    # Check the source-specific closed forms and invariants, independently of eigensolvers.
    t = np.linspace(0, T, 1_001)
    rj = exact_path(CORE["romeo_juliet"]["A"], np.array([1.0, 0.0]), t)
    gs = exact_path(CORE["george_susan"]["A"], np.array([1.0, 0.0]), t)
    np.testing.assert_allclose(rj, np.c_[np.cos(t), -np.sin(t)], atol=2e-13)
    np.testing.assert_allclose(gs, np.c_[np.cos(t) + np.sin(t), -np.sin(t)], atol=2e-13)
    np.testing.assert_allclose((gs[:, 0] + gs[:, 1])**2 + gs[:, 1]**2, 1, atol=2e-13)
    for name, expected in [("romeo_juliet", 0.25), ("george_susan", 0.125)]:
        midpoints = (np.arange(20_000) + 0.5) * 2 * np.pi / 20_000
        state = exact_path(CORE[name]["A"], np.array([1.0, 0.0]), midpoints)
        share = float(np.mean(np.all(state > 0, axis=1)))
        assert abs(share - expected) < 1e-12
        checks[name]["mutual_love_share_one_period_20000_midpoints"] = share
        checks[name]["one_period_return_error"] = float(np.linalg.norm(
            expm(CORE[name]["A"] * 2 * np.pi) - np.eye(2)))

    omega = np.sqrt(3) / 2
    spiral = np.exp(t[:, None] / 2) * np.c_[
        np.cos(omega * t) - np.sin(omega * t) / np.sqrt(3),
        -2 * np.sin(omega * t) / np.sqrt(3)]
    np.testing.assert_allclose(exact_path(OTHER_CASES["exercise_5_3_2"], np.array([1., 0.]), t),
                               spiral, atol=2e-10)
    for key in ["cautious_fading", "cautious_growing"]:
        A = CORE[key]["A"]
        a, b = A[0]
        closed = 0.5 * np.c_[np.exp((a+b)*t) + np.exp((a-b)*t),
                              np.exp((a+b)*t) - np.exp((a-b)*t)]
        np.testing.assert_allclose(exact_path(A, np.array([1., 0.]), t), closed, atol=2e-10)
    robot = exact_path(OTHER_CASES["romeo_robot"], np.array([1., 0.]), t)
    np.testing.assert_allclose(robot, np.c_[np.ones_like(t), 1-np.exp(-t)], atol=2e-13)
    nilpotent = np.array([[1., 1.], [-1., -1.]])
    np.testing.assert_allclose(expm(nilpotent * 3), np.eye(2) + 3*nilpotent, atol=2e-13)
    # A center and a stable node have known closed-form noise covariances.
    _, center_cov = moments_by_quadrature(CORE["romeo_juliet"]["A"], np.array([1., 0.]), NOISE_SD, T)
    np.testing.assert_allclose(center_cov, (INITIAL_SD**2 + NOISE_SD**2*T)*np.eye(2), atol=1e-11)
    _, gs_cov = moments_by_quadrature(CORE["george_susan"]["A"], np.array([1., 0.]), NOISE_SD, T)
    np.testing.assert_allclose(gs_cov, INITIAL_SD**2*np.eye(2) + NOISE_SD**2*T*np.array([[3., -1.5], [-1.5, 1.5]]), atol=1e-11)
    F, Q, _ = transition(CORE["george_susan"]["A"], H, NOISE_SD)
    F2, Q2, _ = transition(CORE["george_susan"]["A"], 2*H, NOISE_SD)
    np.testing.assert_allclose(F2, F@F, atol=1e-13)
    np.testing.assert_allclose(Q2, F@Q@F.T + Q, atol=1e-13)
    checks["exact_noise_transition_composition"] = "passed"
    checks["forward_euler_center_radius_factor_at_T"] = float((1 + H**2)**(STEPS/2))
    return checks


def setup_style():
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "axes.titlesize": 12, "axes.labelsize": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#a9b4bf", "axes.labelcolor": INK,
        "text.color": INK, "xtick.color": INK, "ytick.color": INK,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "svg.hashsalt": "love-affairs-20260927",
    })


def save_figure(fig, directory: Path, name: str):
    directory.mkdir(parents=True, exist_ok=True)
    fig.savefig(directory / f"{name}.png", dpi=180, bbox_inches="tight",
                metadata={"Software": "love-affairs/simulate.py"})
    fig.savefig(directory / f"{name}.svg", bbox_inches="tight", metadata={"Date": None})
    svg = directory / f"{name}.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
    plt.close(fig)


def phase_panel(ax, A, title, labels=("Romeo, R", "Juliet, J"), limit=1.8, duration=8):
    ax.axhspan(0, limit, xmin=0.5, color="#e9f2e9", alpha=0.7, zorder=0)
    axis = np.linspace(-limit, limit, 11)
    X, Y = np.meshgrid(axis, axis)
    U, V = A[0, 0]*X + A[0, 1]*Y, A[1, 0]*X + A[1, 1]*Y
    lengths = np.hypot(U, V)
    U = np.divide(U, lengths, out=np.zeros_like(U), where=lengths > 1e-12)
    V = np.divide(V, lengths, out=np.zeros_like(V), where=lengths > 1e-12)
    ax.quiver(X, Y, U, V, color="#b8c1ca", angles="xy", pivot="mid", scale=25, width=.003)
    F = expm(A * duration / 400)
    backward_F = expm(-A * duration / 400)
    for angle in np.linspace(0, 2*np.pi, 8, endpoint=False) + 0.15:
        start = 1.2 * np.array([np.cos(angle), np.sin(angle)])
        state = start.copy()
        path = [state]
        for _ in range(400):
            state = F @ state
            path.append(state)
        state = start.copy()
        backward = []
        for _ in range(400):
            state = backward_F @ state
            backward.append(state)
        path = np.array(backward[::-1] + path)
        ax.plot(path[:, 0], path[:, 1], color=FIRST, linewidth=1, alpha=.75)
    ax.axhline(0, color="#a9b4bf", linewidth=.6)
    ax.axvline(0, color="#a9b4bf", linewidth=.6)
    ax.plot(0, 0, "o", color=INK, ms=3)
    ax.set(xlim=(-limit, limit), ylim=(-limit, limit), aspect="equal", title=title,
           xlabel=labels[0], ylabel=labels[1])
    ax.set_xticks([-1, 0, 1])
    ax.set_yticks([-1, 0, 1])


def cycle_figure(directory):
    fig, axes = plt.subplots(2, 2, figsize=(10, 8), layout="constrained")
    times = np.linspace(0, 2*np.pi, 1_601)
    for row, key in enumerate(["romeo_juliet", "george_susan"]):
        case = CORE[key]
        state = exact_path(case["A"], np.array([1., 0.]), times)
        ax = axes[row, 0]
        phase_panel(ax, case["A"], case["title"] + ": a closed orbit",
                    (case["first"], case["second"]), limit=1.7, duration=2*np.pi)
        ax.plot(state[:, 0], state[:, 1], color=FIRST, lw=2.5)
        ax.plot(1, 0, "o", color=FIRST, ms=5)
        axes[row, 1].plot(times, state[:, 0], color=FIRST, lw=2, label=case["first"])
        axes[row, 1].plot(times, state[:, 1], color=SECOND, lw=2, label=case["second"])
        both = np.all(state > 1e-12, axis=1)
        axes[row, 1].fill_between(times, -1.6, 1.6, where=both, color="#e0eddf", step="mid")
        axes[row, 1].axhline(0, color="#a9b4bf", lw=.7)
        share = "25%" if row == 0 else "12.5%"
        axes[row, 1].set(title=f"Mutual love for {share} of each cycle",
                         xlabel="Time (one period)", ylabel="Feeling", xlim=(0, 2*np.pi), ylim=(-1.6, 1.6))
        axes[row, 1].set_xticks([0, np.pi/2, np.pi, 3*np.pi/2, 2*np.pi],
                               ["0", "$\\pi/2$", "$\\pi$", "$3\\pi/2$", "$2\\pi$"])
        axes[row, 1].legend(frameon=False, loc="upper right")
    save_figure(fig, directory, "01-cycles")


def cautious_figure(directory):
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), layout="constrained")
    variants = [
        (CORE["cautious_fading"]["A"], "Feelings fade\n$\\kappa=1,\\ \\rho=0.5$: stable node"),
        (CORE["cautious_growing"]["A"], "Love or hostility grows\n$\\kappa=0.5,\\ \\rho=1$: saddle"),
        (OTHER_CASES["cautious_boundary"], "A continuum of steady feelings\n$\\kappa=\\rho=1$: boundary"),
    ]
    for ax, (A, title) in zip(axes, variants):
        phase_panel(ax, A, title)
        ax.plot([-1.8, 1.8], [-1.8, 1.8], "--", color=SECOND, lw=1.2)
    axes[1].plot([-1.8, 1.8], [1.8, -1.8], ":", color=INK, lw=1.4)
    save_figure(fig, directory, "02-cautious")


def exercise_figure(directory):
    fig, axes = plt.subplots(2, 3, figsize=(12, 8), layout="constrained")
    variants = [
        ("exercise_5_3_2", "Escalating cycles\nUnstable spiral"),
        ("out_of_touch", "Reacting only to each other\n$a=b=1$: saddle"),
        ("fire_and_water", "Fire and water\n$a=0.5,\\ b=1$: center"),
        ("peas_in_a_pod", "Identical contrarians\n$a=1,\\ b=-0.5$: unstable node"),
        ("romeo_robot", "The unwavering partner\n$a=1,\\ b=-1$: fixed line"),
    ]
    for ax, (name, title) in zip(axes.flat, variants):
        phase_panel(ax, OTHER_CASES[name], title)
    axes.flat[4].plot([-1.8, 1.8], [-1.8, 1.8], "--", color=SECOND, lw=1.3)
    times = np.linspace(0, 4*np.pi/np.sqrt(3), 801)
    states = exact_path(OTHER_CASES["exercise_5_3_2"], np.array([1., 0.]), times)
    ax = axes.flat[5]
    ax.plot(times, states[:, 0], color=FIRST, lw=2, label="Romeo")
    ax.plot(times, states[:, 1], color=SECOND, lw=2, label="Juliet")
    ax.axhline(0, color="#a9b4bf", lw=.7)
    ax.set(title="An escalating cycle over time\n$R(0)=1,\\ J(0)=0$",
           xlabel="Time (one oscillation)", ylabel="Feeling", xlim=(0, times[-1]))
    ax.legend(frameon=False, fontsize=9)
    save_figure(fig, directory, "03-exercises")


def noise_figure(directory, all_arrays):
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.5), layout="constrained")
    for ax, (key, case) in zip(axes.flat, CORE.items()):
        data = all_arrays[key]["noise"]
        times = data["times"]
        ax.fill_between(times, data["lower"][:, 0], data["upper"][:, 0], color=PALE,
                        label="Middle 95% of runs")
        for n in range(3):
            ax.plot(times, data["paths"][:, n, 0], color=FIRST, alpha=.35, lw=.7)
        ax.plot(times, data["means"][:, 0], color=FIRST, lw=2, label="Simulated mean")
        ax.plot(times, data["exact_means"][:, 0], color=INK, ls="--", lw=1.3, label="Exact mean")
        ax.axhline(0, color="#a9b4bf", lw=.6)
        ax.set(title=case["title"], xlabel="Time", ylabel=case["first"] + "'s feeling", xlim=(0, T))
    axes[0, 0].legend(frameon=False, fontsize=9, loc="upper left")
    save_figure(fig, directory, "04-noisy-trajectories")


def distribution_figure(directory, all_arrays, summaries):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), layout="constrained")
    data = all_arrays["cautious_fading"]["noise"]["endpoints"][:, 0]
    result = summaries["cautious_fading"]["noise"]
    mu, sd = result["theoretical_endpoint_mean"][0], np.sqrt(result["theoretical_endpoint_covariance"][0][0])
    axes[0].hist(data, bins=45, density=True, color=FIRST, alpha=.65, label="10,000 runs")
    xs = np.linspace(mu-4*sd, mu+4*sd, 400)
    axes[0].plot(xs, norm.pdf(xs, mu, sd), color=INK, lw=1.6, label="Exact Gaussian")
    axes[0].set(title="Cautious: near indifference", xlabel="Romeo's feeling at the final time", ylabel="Probability density")
    axes[0].legend(frameon=False, fontsize=9)

    endpoints = all_arrays["cautious_growing"]["noise"]["endpoints"]
    common = np.exp(-T/2) * endpoints.sum(axis=1) / np.sqrt(2)
    result = summaries["cautious_growing"]["noise"]["scaled_common_mode"]
    mu, sd = result["theoretical_mean"], result["theoretical_sd"]
    axes[1].hist(common, bins=45, density=True, color=SECOND, alpha=.65)
    xs = np.linspace(mu-4*sd, mu+4*sd, 400)
    axes[1].plot(xs, norm.pdf(xs, mu, sd), color=INK, lw=1.6)
    axes[1].axvline(0, color=INK, ls=":", lw=1.3)
    axes[1].set(title="Responsive: a sign decides the direction",
                xlabel="Shared feeling with growth removed\n$e^{-T/2}(R+J)/\\sqrt{2}$", ylabel="Probability density")

    bins = np.arange(-.5, 100.51, 1.0)
    for key, color, prediction in [("romeo_juliet", FIRST, 25), ("george_susan", SECOND, 12.5)]:
        fractions = 100 * all_arrays[key]["noise"]["fractions"]
        axes[2].hist(fractions, bins=bins, histtype="step", lw=1.5, color=color, label=CORE[key]["title"])
        axes[2].axvline(prediction, color=color, ls=":", lw=1.2)
    maximum = max(float(all_arrays[key]["noise"]["fractions"].max()) for key in ["romeo_juliet", "george_susan"])
    axes[2].set(title="Noise changes time spent together",
                xlabel="Mutual love (% of sampled time)", ylabel="Runs per 1 percentage point bin",
                xlim=(0, np.ceil(maximum*100/5)*5+1))
    axes[2].legend(frameon=False, fontsize=9)
    save_figure(fig, directory, "05-distributions")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    output = parser.parse_args().output_dir
    output.mkdir(parents=True, exist_ok=True)
    setup_style()
    checks = deterministic_checks()
    summaries, arrays = {}, {}
    for index, (key, case) in enumerate(CORE.items()):
        initial_rng = np.random.default_rng(np.random.SeedSequence([SEED, index, 0]))
        initial = initial_rng.normal(case["mean0"], INITIAL_SD, size=(N, 2))
        summaries[key], arrays[key] = {}, {}
        for arm, sigma in [("initial_only", 0.0), ("noise", NOISE_SD)]:
            summary, data = simulate_case(key, index, sigma, initial)
            summaries[key][arm], arrays[key][arm] = summary, data
            print(f"{key:20s} {arm:12s}: {N:,} paths; endpoint means = {summary['empirical_endpoint_mean']}", flush=True)
    parameters = parameter_experiment()
    results = {
        "protocol": {
            "seed": SEED, "generator": "NumPy PCG64 with SeedSequence([seed, case_index, stream])",
            "streams": {"initial_state": 0, "temporal_shocks": 1, "parameters": 2},
            "case_order": list(CORE), "replicates_per_case_per_arm": N,
            "initial_state_covariance": (INITIAL_SD**2*np.eye(2)).tolist(),
            "temporal_noise_sd_per_sqrt_time": NOISE_SD,
            "observation_intervals": STEPS, "time_step": H, "duration": T,
            "trajectory_total": len(CORE)*2*N,
            "paired_initial_states_between_arms": True,
            "parameter_matrices_total_separate_experiment": len(CORE)*N,
            "parameter_entry_sd": PARAMETER_SD,
            "parameter_distribution": "independent additive normal perturbations, fixed within each matrix; no truncation or rejection",
            "time_fraction_estimator": "1,000 equally spaced left endpoints per path, excluding T",
            "trajectory_plot_bands": "empirical pointwise 2.5th–97.5th percentiles of 10,000 paths",
            "state_transition": "exact matrix exponential with exact integrated Gaussian covariance",
            "python": platform.python_version(), "numpy": np.__version__,
            "scipy": scipy.__version__, "matplotlib": matplotlib.__version__,
        },
        "deterministic_checks": checks, "ensembles": summaries,
        "parameter_sensitivity": parameters,
        "verification": "All closed-form, independent ODE, continuous covariance, transition-composition, and Monte Carlo checks passed.",
    }
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    figures = output / "figures"
    cycle_figure(figures)
    cautious_figure(figures)
    exercise_figure(figures)
    noise_figure(figures, arrays)
    distribution_figure(figures, arrays, summaries)
    print(f"Wrote results.json and five figures (PNG + SVG) to {output}", flush=True)
    print(results["verification"], flush=True)


if __name__ == "__main__":
    main()
