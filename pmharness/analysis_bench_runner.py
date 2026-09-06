from __future__ import annotations

"""Run the analysis-accuracy benchmark across models.

For each model + each question: run a REAL read-only analysis swarm (openai
adapter routed to the model, CodeGraph-injected, against the target repo),
score the full finding claims against the versioned answer contract. No demo substrate
-- this measures real-code analysis quality.
"""

import json
import os
from pmharness.intent import DriverIntent
from pmharness import bridge
from pmharness.analysis_bench import ANALYSIS_QUESTIONS, BENCHMARK_VERSION, score_analysis


def run_analysis_bench(model: str, repo: str, *, worker_mode: str = "inline") -> dict:
    """Return per-question results and the percentage of verified completions."""
    os.environ["HARNESS_REPO"] = repo
    os.environ["HARNESS_SWARM_ADAPTER"] = "openai"
    os.environ["HARNESS_ANALYSIS_MODEL"] = model
    rows = []
    for q in ANALYSIS_QUESTIONS:
        intent = DriverIntent(action="run_swarm", goal=q.task_prompt, roles=["explore"],
                              rationale="bench")
        try:
            res = bridge.execute_intent(intent, worker_mode=worker_mode)
            # body retains the full claim; headline is clipped at 240 characters.
            findings = [a.get("body") or a.get("headline", "") for a in res.artifacts
                        if a.get("type") == "finding"]
            text = json.dumps(findings)
            adapter = res.adapter
        except Exception as e:
            text = ""
            adapter = f"error:{e}"
        sc = score_analysis(q, text)
        sc["adapter"] = adapter
        sc["chars"] = len(text)
        rows.append(sc)
    mean = (sum(r["score"] for r in rows) / len(rows) * 100) if rows else 0.0
    hits = sum(1 for r in rows if r["hit"])
    fabs = sum(1 for r in rows if r["fab"])
    return {"version": BENCHMARK_VERSION, "model": model, "mean": round(mean, 1), "hits": hits, "fabs": fabs,
            "n": len(rows), "rows": rows}
