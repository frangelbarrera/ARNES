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
arnes run path/to/playbook.yaml --output my-run-log.md
```

## Lint

```bash
arnes lint path/to/playbook.yaml   # validate without executing
```
