# Playbooks

A playbook is a YAML file that names the specialists you want and the
order they should run in. ARNES compiles it into a DAG and executes it.

## Minimal example

```yaml
name: hello-world
objective: Plan and write a blog post.
budget_usd: 0.50

steps:
  - id: plan
    specialist: "@planner"
    input:
      task: "Plan a blog post about ARNES."

  - id: write
    specialist: "@coder"
    input: "{{ steps.plan.output }}"
    requires: [plan]

  - id: review
    specialist: "@reviewer"
    input:
      code: "{{ steps.write.output }}"
    requires: [write]
```

## Fields

| Field        | Type     | Required | Description                                        |
|--------------|----------|----------|----------------------------------------------------|
| `name`       | string   | yes      | Playbook name (used in run-log filenames).        |
| `objective`  | string   | yes      | One-sentence description (rendered in the UI).    |
| `budget_usd` | number   | yes      | Hard USD cap for the whole run.                    |
| `steps`      | list     | yes      | Ordered list of step definitions.                 |
| `variables`  | dict     | no       | Initial input variables (merged with `input`).    |

## Step fields

| Field         | Type     | Required | Description                                       |
|---------------|----------|----------|---------------------------------------------------|
| `id`          | string   | yes      | Unique step id (used in `steps.<id>.output`).     |
| `specialist`  | string   | one of   | The specialist to invoke (e.g. `@planner`).       |
| `tool`        | string   | one of   | A built-in tool to invoke directly.               |
| `input`       | dict     | yes      | Input variables (templated with `{{ ... }}`).     |
| `requires`    | list     | no       | Step ids that must complete before this one.      |
| `condition`   | string   | no       | Jinja2 expression; step skipped if false.         |
| `parallel`    | list     | no       | List of step groups to run concurrently.          |

## Template resolution

Inputs are resolved with Jinja2:

- `{{ steps.<id>.output }}` — the output of a previous step.
- `{{ variables.<name> }}` — a playbook-level variable.
- `{{ input.<name> }}` — the run's initial input.

## Run

```bash
arnes run path/to/playbook.yaml
arnes run path/to/playbook.yaml --stream    # step events as they complete
arnes run path/to/playbook.yaml --mock      # $0, no network
arnes run path/to/playbook.yaml --loops     # actor-critic review loop on every step
arnes run path/to/playbook.yaml --output my-run-log.md
```

## Review loops (actor-critic)

Add a `review:` block to any specialist step to enable iterative
refinement. After the specialist produces output, the critic (default
`@reviewer`) evaluates it. If the critic does not approve, the specialist
is re-invoked with the critic's feedback, up to `max_iterations` times.

```yaml
steps:
  - id: write_code
    specialist: "@coder"
    input:
      spec: "Write a Python function that checks if a string is a palindrome"
    review:
      enabled: true
      critic: "@reviewer"          # default; could be @security-auditor
      max_iterations: 3             # default; cap at 1-10
      pass_threshold: 0.8           # default; critic score >= this → approved
      focus: "Check for edge cases and test coverage"
```

You can also enable review loops globally without per-step config:

```bash
arnes run playbook.yaml --loops
```

Every iteration emits `REVIEW_ITERATION` and `REVIEW_COMPLETED` events
to the Thread, so the audit log records what the critic said and why the
loop stopped.

## Lint

```bash
arnes lint path/to/playbook.yaml   # validate without executing
```
