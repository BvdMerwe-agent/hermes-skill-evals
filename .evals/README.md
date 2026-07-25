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
│   ├── prompts.yaml            # Test cases (human-readable YAML)
│   ├── rubric.yaml             # Weighted scoring categories
│   └── transcripts/            # Captured runs (optional, created per-test)
│       └── 2026-07-24-run1.jsonl
```

The shared runner lives at:

```
skills/.evals/
├── skill_eval.py              # CLI scoring engine (transcripts)
├── live_eval.py               # Live LLM eval runner (sends prompts to actual model)
└── README.md                  # This file
```

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

### 3. Live eval against an actual LLM (Ollama)

The `live_eval.py` script sends each prompt to a live model and scores the response in real time. This is the primary mode for **fine-tuning skills** — it tells you if a skill edit improved or regressed model behavior.

**Usage:**

```bash
cd ~/.hermes/skills/.evals

# Local Ollama (no API key needed)
python3 live_eval.py \
  --skill-path ../github/bernard-git-context \
  --model llama3.2 \
  --ollama-url http://localhost:11434

# Ollama with cloud proxy (auto-routes to cloud models)
python3 live_eval.py \
  --skill-path ../github/bernard-git-context \
  --model kimi-k2.6:cloud \
  --ollama-url http://ollama:11434

# Save transcript for later replay
python3 live_eval.py \
  --skill-path ../github/bernard-git-context \
  --model kimi-k2.6:cloud \
  --ollama-url http://ollama:11434 \
  --output-transcript /tmp/results.jsonl

# Replay transcript without re-calling LLM
python3 skill_eval.py \
  --skill-path ../github/bernard-git-context \
  --transcript /tmp/results.jsonl
```

**How it works:**
1. Loads `SKILL.md` and prepends it as a system prompt
2. Sends each prompt from `prompts.yaml` to the model
3. Parses the model response for `REASONING:` and `COMMANDS:` sections
4. Scores the response using the same engine as `skill_eval.py`
5. Prints per-prompt results and a category summary

### 4. Bulk live eval (all skills)

```bash
cd ~/.hermes/skills/.evals
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py \
  --live \
  --model kimi-k2.6:cloud \
  --ollama-url http://ollama:11434
```

## prompts.yaml

A YAML file with a `prompts:` list. Each item is one eval case:

```yaml
prompts:
  - id: bgc-trigger-pos-1
    should_trigger: true
    category: trigger
    prompt: "I need to push this project to GitHub under BvdMerwe-agent"
    expected_reasoning_contains:
      - "not on PATH"
      - "/opt/data/home/bin/gh"
    expected_commands:
      - "/opt/data/home/bin/gh"
    forbidden_commands:
      - "gh auth status"

  - id: bgc-trigger-neg-1
    should_trigger: false
    category: trigger
    prompt: "Configure my DNS records for the home server"
```

### Prompt fields

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique identifier (e.g. `bgc-trigger-pos-1`) |
| `should_trigger` | bool | `true` if skill SHOULD fire, `false` for negative controls |
| `category` | string | Rubric category this prompt belongs to |
| `prompt` | string | The user prompt text |
| `expected_commands` | list | Command substrings that must appear |
| `alt_commands` | list | Alternative commands (also counted as valid) |
| `forbidden_commands` | list | Commands that must NOT appear as standalone commands |
| `min_command_matches` | int | Minimum number of expected patterns to match (default: 1) |
| `expected_reasoning_contains` | list | Phrases reasoning must contain |
| `must_not_execute` | bool | `true` if the skill must produce NO commands at all |

**Trigger evals** should always include both positive (`should_trigger=true`) and negative (`should_trigger=false`) prompts. Negative controls use prompts that are adjacent but not in scope (e.g. "Configure DNS" for a git skill).

## rubric.yaml

```yaml
skill: bernard-git-context
version: "1.0.0"
schema_version: "1.0"
checks:
  - id: trigger
    description: "Skill triggers correctly..."
    weight: 20
  - id: identity
    description: "Correct git identity is enforced..."
    weight: 15
scoring:
  pass_threshold: 70
  excellent_threshold: 90
```

- `id` must match `category` values in `prompts.yaml`
- `weight` determines relative importance (total can be anything, scores are normalized)
- Every category in the rubric must have at least one prompt in `prompts.yaml`

## Transcript Format

A JSONL file where each line is a captured turn:

```json
{"prompt": "Clone the repo BvdMerwe-agent/vdM-menu-tracker", "reasoning": "User wants to clone...", "commands": ["git clone https://github.com/BvdMerwe-agent/vdM-menu-tracker.git"]}
{"prompt": "Configure my DNS records", "reasoning": "This is not a git task.", "commands": []}
```

Keys:
- `prompt` — exact match to prompts.yaml `prompt` field
- `reasoning` — the assistant's internal reasoning (for phrase matching)
- `commands` — list of command strings the assistant executed

For negative triggers (where skill should NOT fire), the turn may be omitted entirely from the transcript. This is the canonical way to represent "skill correctly did not trigger."

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
   - All listed phrases must be present

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

1. Run each prompt from `prompts.yaml` against Hermes with the target skill loaded
2. Capture the assistant's reasoning and commands
3. Write one JSON line per prompt to a `.jsonl` file

Future enhancement: automate transcript capture via a wrapper script that iterates prompts and records tool calls.

## Checklist for New Skill Evals

- [ ] `prompts.yaml` with positive and negative triggers
- [ ] `rubric.yaml` with all categories weighted
- [ ] Dry-run passes validation
- [ ] At least one transcript scored
- [ ] Overall score ≥ 70 (PASS) before considering the skill reliable

## References

- [SkillsBench: Benchmarking Agent Skills](https://arxiv.org/abs/2602.12670) — academic benchmark for skill effectiveness
- [OpenAI: Testing Agent Skills Systematically with Evals](https://developers.openai.com/blog/eval-skills) — practical guide with `codex exec --json` pattern
- [Skill Coverage: Test Adequacy Metric](https://arxiv.org/html/2606.20659) — measuring how well evals cover skill behavior
