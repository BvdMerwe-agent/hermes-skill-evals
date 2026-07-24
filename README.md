# Skill Evaluation Methodology

## Overview

This directory (`~/.hermes/skills/.evals/`) contains the tooling and methodology for systematically evaluating Hermes custom skills. Inspired by [SkillsBench](https://arxiv.org/abs/2602.12670) and [OpenAI's eval-skills blog](https://developers.openai.com/blog/eval-skills), the approach is:

1. **Prompts** — define what the skill should and should NOT trigger on
2. **Transcripts** — capture actual assistant turns (reasoning + commands)
3. **Checks** — deterministic verifiers that score behavior
4. **Rubric** — weighted categories with pass/excellent thresholds

## File Structure

Each skill gets an `evals/` subdirectory:

```
skills/<category>/<skill-name>/
├── SKILL.md                    # The skill itself
├── evals/
│   ├── prompts.csv             # Test cases
│   ├── rubric.json             # Weighted scoring categories
│   └── transcripts/            # Captured runs (optional, created per-test)
│       └── 2026-07-24-run1.jsonl
```

The shared runner lives at:

```
skills/.evals/
├── skill_eval.py              # CLI scoring engine
└── README.md                  # This file
```

## prompts.csv

A CSV with one row per eval prompt. Required columns:

| Column | Description |
|---|---|
| `id` | Unique identifier (e.g. `bgc-trigger-pos-1`) |
| `should_trigger` | `true` if skill SHOULD fire, `false` for negative controls |
| `category` | Rubric category this prompt belongs to |
| `prompt` | The user prompt text |
| `expected_commands` | Semicolon-separated command substrings that must appear |
| `alt_commands` | Semicolon-separated alternatives (also counted as valid) |
| `forbidden_commands` | Semicolon-separated commands that must NOT appear |
| `min_command_matches` | Minimum number of expected patterns to match (default: 1) |
| `expected_reasoning_contains` | Semicolon-separated phrases reasoning must contain |
| `must_not_execute` | `true` if the skill must produce NO commands at all |

**Trigger evals** should always include both positive (`should_trigger=true`) and negative (`should_trigger=false`) prompts. Negative controls use prompts that are adjacent but not in scope (e.g. "Configure DNS" for a git skill).

## rubric.json

```json
{
  "skill": "bernard-git-context",
  "version": "1.0.0",
  "schema_version": "1.0",
  "checks": [
    {"id": "trigger", "description": "...", "weight": 20},
    {"id": "identity", "description": "...", "weight": 15}
  ],
  "scoring": {"pass_threshold": 70, "excellent_threshold": 90}
}
```

- `id` must match `category` values in `prompts.csv`
- `weight` determines relative importance (total can be anything, scores are normalized)
- Every category in the rubric must have at least one prompt in `prompts.csv`

## Transcript Format

A JSONL file where each line is a captured turn:

```json
{"prompt": "Clone the repo BvdMerwe-agent/vdM-menu-tracker", "reasoning": "User wants to clone...", "commands": ["git clone https://github.com/BvdMerwe-agent/vdM-menu-tracker.git"]}
{"prompt": "Configure my DNS records", "reasoning": "This is not a git task.", "commands": []}
```

Keys:
- `prompt` — exact match to prompts.csv `prompt` column
- `reasoning` — the assistant's internal reasoning (for phrase matching)
- `commands` — list of command strings the assistant executed

For negative triggers (where skill should NOT fire), the turn may be omitted entirely from the transcript. This is the canonical way to represent "skill correctly did not trigger."

## Running Evals

### 1. Validate eval files (dry-run)

```bash
cd ~/.hermes/skills/.evals
python3 skill_eval.py --skill-path ../github/bernard-git-context --dry-run
```

Checks:
- All prompts have IDs, prompt text, and categories
- No duplicate IDs
- All rubric categories have at least one prompt
- All prompt categories exist in the rubric
- Summarizes what will be checked

### 2. Score against a transcript

```bash
python3 skill_eval.py \
  --skill-path ../github/bernard-git-context \
  --transcript transcripts/run-2026-07-24.jsonl
```

Produces a report like:

```
======================================================================
 SKILL EVAL REPORT: bernard-git-context v1.0.0
======================================================================

  Overall Score: 85.2/100  [PASS]
  Thresholds:    PASS ≥ 70, EXCELLENT ≥ 90

----------------------------------------------------------------------
Category               Passed    Total     Rate   Weight
----------------------------------------------------------------------
✓ trigger                   5        6    83.3%       20
✓ identity                  2        2   100.0%       15
...
----------------------------------------------------------------------

  Per-Prompt Results:
  ------------------------------------------------------------------
  [✓ PASS] bgc-trigger-pos-1         (trigger)
  [✗ FAIL] bgc-trigger-neg-1         (trigger)
           → False positive: skill triggered when it should not have
  ...
```

## Scoring Rules

### Per-prompt checks

1. **Trigger correctness**
   - If `should_trigger=true` and no turn → FAIL (skill didn't fire)
   - If `should_trigger=false` and turn exists → FAIL (false positive)
   - If `should_trigger=false` and no turn → PASS

2. **Expected commands**
   - At least `min_command_matches` patterns from `expected_commands` + `alt_commands` must appear in the command list
   - Substring matching (e.g. `git clone` matches `git clone https://...`)

3. **Forbidden commands**
   - Must NOT appear as a **standalone** command (not as a substring inside a longer path)
   - Example: `gh auth status` is forbidden, but `/opt/data/home/bin/gh auth status` is allowed

4. **Reasoning phrases**
   - Case-insensitive substring match
   - All semicolon-separated phrases must be present

5. **Must not execute**
   - Command list must be empty

### Category scoring

```
category_score = (passed_prompts / total_prompts_in_category) × 100
overall_score = Σ(category_score × weight) / Σ(weights)
```

### Status thresholds

| Score | Status |
|---|---|
| ≥ 90 | EXCELLENT |
| ≥ 70 | PASS |
| < 70 | FAIL |

## Creating Transcripts

Transcripts are currently captured manually or via automation. To create one:

1. Run each prompt from `prompts.csv` against Hermes with the target skill loaded
2. Capture the assistant's reasoning and commands
3. Write one JSON line per prompt to a `.jsonl` file

Future enhancement: automate transcript capture via a wrapper script that iterates prompts and records tool calls.

## Checklist for New Skill Evals

- [ ] `prompts.csv` with positive and negative triggers
- [ ] `rubric.json` with all categories weighted
- [ ] Dry-run passes validation
- [ ] At least one transcript scored
- [ ] Overall score ≥ 70 (PASS) before considering the skill reliable

## References

- [SkillsBench: Benchmarking Agent Skills](https://arxiv.org/abs/2602.12670) — academic benchmark for skill effectiveness
- [OpenAI: Testing Agent Skills Systematically with Evals](https://developers.openai.com/blog/eval-skills) — practical guide with `codex exec --json` pattern
- [Skill Coverage: Test Adequacy Metric](https://arxiv.org/html/2606.20659) — measuring how well evals cover skill behavior
