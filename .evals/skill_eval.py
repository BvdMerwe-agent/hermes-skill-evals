#!/usr/bin/env python3
"""
Skill Eval Runner — score a Hermes skill against its eval definitions.

Usage:
    python skill_eval.py --skill-path ~/.hermes/skills/github/bernard-git-context --transcript transcript.jsonl
    python skill_eval.py --skill-path ~/.hermes/skills/github/bernard-git-context --dry-run

A transcript is a JSONL file where each line is a JSON object representing
one assistant turn. Minimum shape:
    {"prompt": "...", "reasoning": "...", "commands": ["cmd1", "cmd2"]}

If --transcript is omitted, the script runs in "dry-run" mode: it validates
that prompts.yaml and rubric.yaml are well-formed and prints a summary of
what *would* be checked for each prompt.
"""

import argparse
import csv
import json
import pathlib
import re
import sys
from typing import Any

import yaml


def load_prompts(skill_path: pathlib.Path) -> list[dict]:
    """Load evals/prompts.yaml from a skill directory."""
    prompts_file = skill_path / "evals" / "prompts.yaml"
    if not prompts_file.exists():
        print(f"ERROR: prompts.yaml not found at {prompts_file}", file=sys.stderr)
        sys.exit(1)

    with open(prompts_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    prompts = data.get("prompts", [])
    for p in prompts:
        # Normalise booleans
        for key in ("should_trigger", "must_not_execute"):
            if key in p and isinstance(p[key], str):
                p[key] = p[key].strip().lower() == "true"
    return prompts


def load_rubric(skill_path: pathlib.Path) -> dict:
    """Load evals/rubric.yaml from a skill directory."""
    rubric_file = skill_path / "evals" / "rubric.yaml"
    if not rubric_file.exists():
        print(f"ERROR: rubric.yaml not found at {rubric_file}", file=sys.stderr)
        sys.exit(1)
    with open(rubric_file, encoding="utf-8") as f:
        return yaml.safe_load(f)


def split_semicolon(value: str | None | list) -> list[str]:
    """Split a semicolon-separated string or list, stripping whitespace, skipping empties."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if v is not None and str(v).strip()]
    if not value:
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def check_commands_present(commands: list[str], expected_raw: str) -> tuple[bool, list[str]]:
    """Check that at least one expected command pattern is present in the command list."""
    expected_patterns = split_semicolon(expected_raw)
    if not expected_patterns:
        return True, []
    found = []
    for pattern in expected_patterns:
        for cmd in commands:
            if pattern in cmd:
                found.append(pattern)
                break
    # Pass if we found at least one match
    passed = len(found) >= 1
    return passed, found


def check_commands_present_min(commands: list[str], expected_raw: str, min_matches: int) -> tuple[bool, list[str]]:
    """Check that at least min_matches expected command patterns are present."""
    expected_patterns = split_semicolon(expected_raw)
    if not expected_patterns:
        return True, []
    found = []
    for pattern in expected_patterns:
        for cmd in commands:
            if pattern in cmd:
                found.append(pattern)
                break
    passed = len(found) >= min_matches
    return passed, found


def check_forbidden_absent(commands: list[str], forbidden_raw: str) -> tuple[bool, list[str]]:
    """Check that NO forbidden command pattern is present as a standalone command.
    
    Matches only when the forbidden string is a distinct command (not inside a path).
    Example: 'gh auth status' matches 'gh auth status' but NOT
    '/opt/data/home/bin/gh auth status'.
    """
    forbidden_patterns = split_semicolon(forbidden_raw)
    if not forbidden_patterns:
        return True, []
    violations = []
    for pattern in forbidden_patterns:
        escaped = re.escape(pattern)
        # Match when preceded by start-of-string, whitespace, or command separator
        # and followed by end-of-string, whitespace, or separator
        regex = re.compile(rf"(^|[;\s\|&]){escaped}([;\s\|&]|$)")
        for cmd in commands:
            if regex.search(cmd):
                violations.append(pattern)
                break
    passed = len(violations) == 0
    return passed, violations


def check_reasoning(reasoning: str, expected_raw: str) -> tuple[bool, list[str]]:
    """Check that all expected reasoning substrings appear in reasoning text."""
    expected_phrases = split_semicolon(expected_raw)
    if not expected_phrases:
        return True, []
    missing = []
    for phrase in expected_phrases:
        if phrase.lower() not in reasoning.lower():
            missing.append(phrase)
    passed = len(missing) == 0
    return passed, missing


def score_prompt(
    prompt_def: dict,
    turn: dict[str, Any] | None,
) -> dict:
    """Score a single prompt definition against a captured turn."""
    results = {
        "id": prompt_def["id"],
        "prompt": prompt_def["prompt"],
        "category": prompt_def.get("category", ""),
        "should_trigger": prompt_def.get("should_trigger", True),
        "passed": True,
        "checks": {},
        "errors": [],
    }

    # If no turn captured, the skill didn't trigger at all.
    if turn is None:
        if results["should_trigger"]:
            results["passed"] = False
            results["errors"].append("Skill did not trigger (no turn captured)")
        else:
            results["checks"]["trigger"] = {"passed": True, "note": "Correctly did not trigger"}
        return results

    # The skill produced a turn. If it should NOT have triggered, that's a false positive.
    if not results["should_trigger"]:
        results["passed"] = False
        results["errors"].append("False positive: skill triggered when it should not have")
        results["checks"]["trigger"] = {"passed": False, "note": "False positive"}
        return results

    # Extract fields from turn
    reasoning = turn.get("reasoning", "")
    commands = turn.get("commands", [])

    # --- Trigger check (implicitly passed if we got here) ---
    results["checks"]["trigger"] = {"passed": True, "note": "Skill triggered correctly"}

    # --- Expected commands ---
    expected_cmds = prompt_def.get("expected_commands", "")
    alt_cmds = prompt_def.get("alt_commands", "")
    min_matches_raw = prompt_def.get("min_command_matches", "")
    min_matches = int(min_matches_raw) if min_matches_raw and str(min_matches_raw).isdigit() else 1

    if expected_cmds:
        # Combine expected + alternative commands for matching
        all_expected = expected_cmds
        if alt_cmds:
            all_expected += ";" + alt_cmds
        passed, found = check_commands_present_min(commands, all_expected, min_matches)
        results["checks"]["commands"] = {
            "passed": passed,
            "expected": split_semicolon(expected_cmds),
            "alt": split_semicolon(alt_cmds),
            "found": found,
            "required_min": min_matches,
        }
        if not passed:
            results["passed"] = False
            results["errors"].append(
                f"Expected at least {min_matches} command match(es), found {len(found)}. "
                f"Missing from: {split_semicolon(expected_cmds)}"
            )

    # --- Forbidden commands ---
    forbidden_cmds = prompt_def.get("forbidden_commands", "")
    if forbidden_cmds:
        passed, violations = check_forbidden_absent(commands, forbidden_cmds)
        results["checks"]["forbidden"] = {
            "passed": passed,
            "forbidden": split_semicolon(forbidden_cmds),
            "violations": violations,
        }
        if not passed:
            results["passed"] = False
            results["errors"].append(f"Forbidden commands found: {violations}")

    # --- Reasoning checks ---
    reasoning_expected = prompt_def.get("expected_reasoning_contains", "")
    if reasoning_expected:
        passed, missing = check_reasoning(reasoning, reasoning_expected)
        results["checks"]["reasoning"] = {
            "passed": passed,
            "expected": split_semicolon(reasoning_expected),
            "missing": missing,
        }
        if not passed:
            results["passed"] = False
            results["errors"].append(f"Reasoning missing expected phrases: {missing}")

    # --- Must not execute ---
    must_not_execute = prompt_def.get("must_not_execute", False)
    if must_not_execute:
        has_commands = len(commands) > 0
        results["checks"]["no_execution"] = {
            "passed": not has_commands,
            "commands_executed": commands,
        }
        if has_commands:
            results["passed"] = False
            results["errors"].append(f"Should not execute commands, but executed: {commands}")

    return results


def compute_category_scores(results: list[dict], rubric: dict) -> dict:
    """Group results by category and compute per-category pass rates."""
    # Collect all unique categories from both rubric and results
    categories = {check["id"] for check in rubric.get("checks", [])}
    category_scores = {}

    for cat_id in categories:
        cat_results = [r for r in results if r["category"] == cat_id]
        if not cat_results:
            category_scores[cat_id] = None  # No evals for this category
            continue
        passed = sum(1 for r in cat_results if r["passed"])
        total = len(cat_results)
        category_scores[cat_id] = {
            "passed": passed,
            "total": total,
            "rate": round(passed / total * 100, 1),
        }

    return category_scores


def compute_overall_score(category_scores: dict, rubric: dict) -> dict:
    """Compute weighted overall score from category scores and rubric weights."""
    total_weight = 0
    weighted_sum = 0.0
    missing_categories = []

    for check in rubric.get("checks", []):
        cat_id = check["id"]
        weight = check.get("weight", 0)
        score_info = category_scores.get(cat_id)

        if score_info is None:
            missing_categories.append(cat_id)
            continue

        total_weight += weight
        weighted_sum += score_info["rate"] * weight

    if total_weight == 0:
        return {"score": 0, "status": "ERROR", "missing": missing_categories}

    overall = round(weighted_sum / total_weight, 1)
    pass_threshold = rubric.get("scoring", {}).get("pass_threshold", 70)
    excellent_threshold = rubric.get("scoring", {}).get("excellent_threshold", 90)

    if overall >= excellent_threshold:
        status = "EXCELLENT"
    elif overall >= pass_threshold:
        status = "PASS"
    else:
        status = "FAIL"

    return {
        "score": overall,
        "status": status,
        "pass_threshold": pass_threshold,
        "excellent_threshold": excellent_threshold,
        "missing_categories": missing_categories,
    }


def print_report(results: list[dict], category_scores: dict, overall: dict, rubric: dict):
    """Pretty-print a scoring report."""
    print("=" * 70)
    print(f" SKILL EVAL REPORT: {rubric.get('skill', 'unknown')} v{rubric.get('version', '?')}")
    print("=" * 70)
    print()

    # Overall
    print(f"  Overall Score: {overall['score']}/100  [{overall['status']}]")
    print(f"  Thresholds:    PASS ≥ {overall['pass_threshold']}, EXCELLENT ≥ {overall['excellent_threshold']}")
    if overall.get("missing_categories"):
        print(f"  ⚠ No evals found for categories: {', '.join(overall['missing_categories'])}")
    print()

    # Category breakdown
    print("-" * 70)
    print(f"{'Category':<20} {'Passed':>8} {'Total':>8} {'Rate':>8} {'Weight':>8}")
    print("-" * 70)
    for check in rubric.get("checks", []):
        cat_id = check["id"]
        weight = check.get("weight", 0)
        score_info = category_scores.get(cat_id)
        if score_info is None:
            print(f"{cat_id:<20} {'N/A':>8} {'N/A':>8} {'N/A':>8} {weight:>8}")
        else:
            marker = "✓" if score_info["rate"] == 100 else ("✗" if score_info["rate"] < 70 else "~")
            print(f"{marker} {cat_id:<18} {score_info['passed']:>8} {score_info['total']:>8} {score_info['rate']:>7}% {weight:>8}")
    print("-" * 70)
    print()

    # Per-prompt details
    print("  Per-Prompt Results:")
    print("  " + "-" * 66)
    for r in results:
        marker = "✓ PASS" if r["passed"] else "✗ FAIL"
        print(f"  [{marker:6}] {r['id']:<25} ({r['category']})")
        if r["errors"]:
            for err in r["errors"]:
                print(f"           → {err}")
    print()


def load_transcript(path: pathlib.Path) -> dict[str, dict]:
    """Load a JSONL transcript keyed by prompt text."""
    turns = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            turn = json.loads(line)
            prompt = turn.get("prompt", "")
            if prompt:
                turns[prompt] = turn
    return turns


def dry_run(skill_path: pathlib.Path, prompts: list[dict], rubric: dict):
    """Validate eval files and show what would be checked without running."""
    print("=" * 70)
    print(f" DRY RUN: {rubric.get('skill', 'unknown')}")
    print("=" * 70)
    print()

    # Validation
    errors = []
    ids_seen = set()
    for p in prompts:
        if not p.get("id"):
            errors.append("Prompt missing 'id'")
        elif p["id"] in ids_seen:
            errors.append(f"Duplicate prompt id: {p['id']}")
        ids_seen.add(p.get("id", ""))

        if not p.get("prompt"):
            errors.append(f"Prompt {p.get('id', '?')} missing 'prompt' text")

        if not p.get("category"):
            errors.append(f"Prompt {p.get('id', '?')} missing 'category'")

    # Check all rubric categories appear in prompts
    rubric_cats = {c["id"] for c in rubric.get("checks", [])}
    prompt_cats = {p["category"] for p in prompts}
    missing = rubric_cats - prompt_cats
    if missing:
        errors.append(f"Rubric categories with no eval prompts: {missing}")

    extra = prompt_cats - rubric_cats
    if extra:
        errors.append(f"Prompt categories not in rubric: {extra}")

    if errors:
        print("VALIDATION ERRORS:")
        for err in errors:
            print(f"  ✗ {err}")
        print()
        sys.exit(1)
    else:
        print("✓ All eval files are valid.")
        print()

    # Summary
    print(f"Total prompts:  {len(prompts)}")
    print(f"Trigger=true:   {sum(1 for p in prompts if p.get('should_trigger'))}")
    print(f"Trigger=false:  {sum(1 for p in prompts if not p.get('should_trigger'))}")
    print()

    print("Rubric:")
    total_weight = sum(c.get("weight", 0) for c in rubric.get("checks", []))
    for check in rubric.get("checks", []):
        cat_id = check["id"]
        weight = check.get("weight", 0)
        count = sum(1 for p in prompts if p["category"] == cat_id)
        print(f"  {cat_id:<20} weight={weight:<4} prompts={count}")
    print(f"  {'TOTAL':<20} weight={total_weight}")
    print()

    print("Sample of what gets checked:")
    for p in prompts[:3]:
        print(f"\n  [{p['id']}] should_trigger={p.get('should_trigger')}")
        print(f"    Prompt: {p['prompt'][:70]}...")
        if p.get("expected_commands"):
            print(f"    Expected commands: {split_semicolon(p['expected_commands'])}")
        if p.get("forbidden_commands"):
            print(f"    Forbidden commands: {split_semicolon(p['forbidden_commands'])}")
        if p.get("expected_reasoning_contains"):
            print(f"    Reasoning must contain: {split_semicolon(p['expected_reasoning_contains'])}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Skill Eval Runner")
    parser.add_argument("--skill-path", required=True, type=pathlib.Path,
                        help="Path to skill directory containing evals/")
    parser.add_argument("--transcript", type=pathlib.Path,
                        help="Path to JSONL transcript file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate eval files without scoring")
    args = parser.parse_args()

    prompts = load_prompts(args.skill_path)
    rubric = load_rubric(args.skill_path)

    if args.dry_run or not args.transcript:
        dry_run(args.skill_path, prompts, rubric)
        return

    # Load transcript
    turns = load_transcript(args.transcript)

    # Score each prompt
    results = []
    for prompt_def in prompts:
        prompt_text = prompt_def["prompt"]
        turn = turns.get(prompt_text)
        result = score_prompt(prompt_def, turn)
        results.append(result)

    # Compute scores
    category_scores = compute_category_scores(results, rubric)
    overall = compute_overall_score(category_scores, rubric)

    # Report
    print_report(results, category_scores, overall, rubric)


if __name__ == "__main__":
    main()
