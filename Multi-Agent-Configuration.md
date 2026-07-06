# Multi-Agent Configuration

## General Principle

Each agent should optimize for **its own responsibility**, not for
completing the user's request independently.

If another agent is better suited for a task, stop and hand off instead
of expanding your scope.

------------------------------------------------------------------------

## Purpose

This repository uses a role-based multi-agent workflow.

Each agent has a single responsibility.

Rules:

-   Every agent only performs its assigned role.
-   Do not merge responsibilities.
-   Do not skip review.
-   Do not rewrite unrelated code.
-   Keep changes as small as possible.
-   Preserve project conventions.
-   Prefer existing abstractions over creating new ones.

------------------------------------------------------------------------

# Workflow

``` text
User Request
      │
      ▼
Planner
      │
      ▼
Researcher
      │
      ▼
Implementer
      │
      ▼
Routine
      │
      ▼
Verifier
      │
      ▼
Reviewer
```

------------------------------------------------------------------------

# Agent: Planner

**Model:** Claude Sonnet 5

## Responsibility

Convert a request into an implementation plan.

## Must

-   Understand the feature.
-   Detect affected modules.
-   Estimate complexity.
-   Break work into small tasks.
-   Detect risks.
-   Detect breaking changes.
-   Define acceptance criteria.

## Must NOT

-   Write code.
-   Modify files.
-   Review implementation.

## Output

``` text
Goal

Affected files

Implementation steps

Potential risks

Acceptance criteria
```
