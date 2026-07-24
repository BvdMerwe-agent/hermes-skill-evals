#!/usr/bin/env python3
"""
Weekly Skill Eval Runner — run evaluations across all skills with eval definitions.

Usage:
    # Dry-run all discovered skills
    python3 run_evals.py

    # Dry-run a single skill
    python3 run_evals.py --skill-path ~/.hermes/skills/github/bernard-git-context

    # Score with transcripts
    python3 run_evals.py --skill-path ~/.hermes/skills/github/bernard-git-context \
        --transcript-path /mnt/data/transcripts/bernard-git-context/latest.jsonl

    # Generate markdown report
    python3 run_evals.py --report --output /tmp/skill-eval-report-$(date +%Y%m%d).md

The script discovers skills by walking the ~/.hermes/skills/ tree and looking for:
    evals/prompts.yaml + evals/rubric.yaml
"""

import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any

# Base paths
SKILLS_ROOT = pathlib.Path("/home/hermeswebui/.hermes/skills")
EVAL_RUNNER = SKILLS_ROOT / ".evals" / "skill_eval.py"


def discover_skills(skills_root: pathlib.Path) -> list[pathlib.Path]:
    """Walk skills tree and find directories with both prompts.yaml and rubric.yaml."""
    skills = []
    if not skills_root.exists():
        return skills

    # Walk 3 levels deep: skills/<category>/<skill-name>/evals/
    for category_dir in skills_root.iterdir():
        if not category_dir.is_dir():
            continue
        if category_dir.name.startswith("."):
            continue
        for skill_dir in category_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            evals_dir = skill_dir / "evals"
            prompts = evals_dir / "prompts.yaml"
            rubric = evals_dir / "rubric.yaml"
            if prompts.exists() and rubric.exists():
                skills.append(skill_dir)

    return sorted(skills)


def run_skill_eval(skill_path: pathlib.Path, transcript_path: pathlib.Path | None = None) -> dict[str, Any]:
    """Run skill_eval.py for a single skill. Returns parsed result."""
    cmd = [sys.executable, str(EVAL_RUNNER), "--skill-path", str(skill_path)]
    if transcript_path and transcript_path.exists():
        cmd.extend(["--transcript", str(transcript_path)])
    else:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(EVAL_RUNNER.parent),
        )
    except subprocess.TimeoutExpired:
        return {
            "skill": skill_path.name,
            "category": skill_path.parent.name,
            "path": str(skill_path),
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": "TIMEOUT after 30s",
            "score": None,
            "pass": None,
        }

    return {
        "skill": skill_path.name,
        "category": skill_path.parent.name,
        "path": str(skill_path),
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "score": _extract_score(result.stdout),
        "pass": _extract_pass(result.stdout),
    }


def _extract_score(stdout: str) -> float | None:
    """Try to extract the overall score from skill_eval.py output."""
    m = re.search(r"Overall Score:\s*([\d.]+)", stdout)
    if m:
        return float(m.group(1))
    return None


def _extract_pass(stdout: str) -> str | None:
    """Try to extract PASS/FAIL/EXCELLENT status."""
    for line in stdout.splitlines():
        if "Overall Score:" in line:
            if "PASS" in line:
                return "PASS"
            if "EXCELLENT" in line:
                return "EXCELLENT"
            if "FAIL" in line:
                return "FAIL"
    return None


def parse_dry_run(stdout: str) -> dict[str, Any]:
    """Extract stats from dry-run output."""
    stats = {"total_prompts": 0, "trigger_true": 0, "trigger_false": 0, "rubric_categories": 0}

    total = re.search(r"Total prompts:\s+(\d+)", stdout)
    if total:
        stats["total_prompts"] = int(total.group(1))

    t_true = re.search(r"Trigger=true:\s+(\d+)", stdout)
    if t_true:
        stats["trigger_true"] = int(t_true.group(1))

    t_false = re.search(r"Trigger=false:\s+(\d+)", stdout)
    if t_false:
        stats["trigger_false"] = int(t_false.group(1))

    # Count rubric categories
    for line in stdout.splitlines():
        if re.match(r"^\s+\S+\s+weight=\d+", line):
            stats["rubric_categories"] += 1

    return stats


def generate_report(results: list[dict], skills_root: pathlib.Path) -> str:
    """Build a markdown report from all results."""
    lines = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines.append(f"# Skill Eval Report — {now}")
    lines.append("")

    # Summary
    total_skills = len(results)
    ok_skills = sum(1 for r in results if r["ok"])
    scored_skills = sum(1 for r in results if r["score"] is not None)

    lines.append("## Summary")
    lines.append(f"- Skills evaluated: {total_skills}")
    lines.append(f"- Skills passing validation: {ok_skills}/{total_skills}")
    lines.append(f"- Skills with transcripts scored: {scored_skills}/{total_skills}")
    lines.append("")

    # Per-skill details
    lines.append("## Results by Skill")
    lines.append("")

    regressions = []

    for r in sorted(results, key=lambda x: (x["category"], x["skill"])):
        lines.append(f"### {r['category']}/{r['skill']}")
        lines.append(f"- Path: `{r['path']}`")

        if not r["ok"]:
            lines.append(f"- **Status: FAILED validation**")
            if r["stderr"]:
                lines.append(f"- Error: `{r['stderr'][:200]}`")
            regressions.append(f"{r['category']}/{r['skill']}: eval file validation failed")
            lines.append("")
            continue

        lines.append(f"- Status: OK")

        if r["score"] is not None:
            status = r["pass"] or "UNKNOWN"
            lines.append(f"- Score: {r['score']:.1f}/100 [{status}]")
            if status == "FAIL":
                regressions.append(f"{r['category']}/{r['skill']}: score {r['score']:.1f} below PASS threshold")
        else:
            lines.append(f"- Score: N/A (dry-run, no transcript)")

        # Include dry-run stats if available
        if r["stdout"]:
            stats = parse_dry_run(r["stdout"])
            lines.append(f"- Prompts: {stats['total_prompts']} ({stats['trigger_true']} pos triggers, {stats['trigger_false']} neg triggers)")
            lines.append(f"- Rubric categories: {stats['rubric_categories']}")

        lines.append("")

    # Regressions section
    lines.append("## Regressions")
    lines.append("")
    if regressions:
        for reg in regressions:
            lines.append(f"- ⚠️ {reg}")
    else:
        lines.append("No regressions detected.")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"_Generated by weekly-skill-evals at {now}_")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Weekly skill evaluation runner")
    parser.add_argument("--skill-path", type=pathlib.Path, help="Evaluate a single skill instead of all")
    parser.add_argument("--transcript-path", type=pathlib.Path, help="Path to transcript JSONL for scoring")
    parser.add_argument("--report", action="store_true", help="Generate markdown report")
    parser.add_argument("--output", type=pathlib.Path, help="Write report to file")
    args = parser.parse_args()

    if not EVAL_RUNNER.exists():
        print(f"ERROR: Eval runner not found at {EVAL_RUNNER}", file=sys.stderr)
        sys.exit(1)

    if args.skill_path:
        skills = [args.skill_path.resolve()]
    else:
        skills = discover_skills(SKILLS_ROOT)

    if not skills:
        print("No skills with eval definitions found.", file=sys.stderr)
        sys.exit(0)

    print(f"Evaluating {len(skills)} skill(s)...")
    print()

    results = []
    for skill_path in skills:
        print(f"  → {skill_path.parent.name}/{skill_path.name} ...", end=" ", flush=True)
        result = run_skill_eval(skill_path, args.transcript_path)
        results.append(result)
        if result["ok"]:
            if result["score"] is not None:
                status = result["pass"] or "UNKNOWN"
                print(f"OK ({result['score']:.1f} [{status}])")
            else:
                print("OK (dry-run)")
        else:
            print(f"FAILED (exit {result['exit_code']})")
            if result["stderr"]:
                print(f"    stderr: {result['stderr'][:150]}")

    print()

    if args.report or args.output:
        report = generate_report(results, SKILLS_ROOT)
        if args.output:
            args.output.write_text(report, encoding="utf-8")
            print(f"Report written to: {args.output}")
        else:
            print(report)
    else:
        # Summary only
        ok_count = sum(1 for r in results if r["ok"])
        print(f"Done. {ok_count}/{len(results)} skills passed validation.")


if __name__ == "__main__":
    main()
