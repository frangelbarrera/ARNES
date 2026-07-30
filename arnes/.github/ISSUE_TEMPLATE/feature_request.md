---
name: Feature request
about: Suggest a new feature, specialist, playbook, or improvement for ARNES
title: "[feat] "
labels: ["enhancement", "triage"]
assignees: []
---

# Feature request

Thank you for thinking about how ARNES can be better! Please fill out the
sections below so we can discuss the proposal before any code is written.

## The problem

What problem are you trying to solve? Who is affected by it? Be specific —
link to a real workflow, repo, or pain point if you can.

> "I want to run ARNES playbooks from inside my editor, but today I have to
> drop to a terminal and ..."

## Proposed solution

Describe what you would like ARNES to do. Include a snippet of what the
manual, CLI, or API would look like if the feature existed.

```yaml
# Example of how the new feature would look in a playbook
name: my-new-playbook
objective: ...
budget_usd: 0.10

steps:
  - id: ...
    specialist: "@my-new-specialist"
    input:
      ...
```

## Alternatives considered

What other ways have you tried to solve this? Why are they not enough?

- Alternative A: ... — but it doesn't handle ...
- Alternative B: ... — but it costs ...

## Scope and impact

- **Who benefits?** [e.g. all users, only Latam users, only enterprise users]
- **Estimated complexity:** [small / medium / large]
- **Breaking change?** [yes / no]
- **Aligns with roadmap?** [link to the v0.x milestone it fits, if applicable]

## Additional context

Screenshots, mockups, links to related issues, prior art in other tools
(LangChain, CrewAI, OpenAI Agents SDK, etc.) — anything that helps us
understand the request.

---

**Checklist before submitting:**

- [ ] I have searched [existing issues](https://github.com/frangelbarrera/ARNES/issues) and [Discussions](https://github.com/frangelbarrera/ARNES/discussions) for prior requests.
- [ ] I am open to iterating on the design before implementation.
- [ ] (Optional) I am willing to submit a PR if the proposal is accepted.
