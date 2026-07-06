# Multi-Agent Configuration


## General Principle

Each agent should optimize for **its own responsibility**, not for completing the user's request independently.

If another agent is better suited for a task, stop and hand off instead of expanding your scope.



\## Purpose



This repository uses a role-based multi-agent workflow.



Each agent has a single responsibility.



Rules:



\- Every agent only performs its assigned role.

\- Do not merge responsibilities.

\- Do not skip review.

\- Do not rewrite unrelated code.

\- Keep changes as small as possible.

\- Preserve project conventions.

\- Prefer existing abstractions over creating new ones.





\---



\# Workflow



```

User Request

           │

           ▼

Planner

&#x20;     │

&#x20;     ▼

Researcher

&#x20;     │

&#x20;     ▼

Implementer

&#x20;     │

&#x20;     ▼

Routine

&#x20;     │

&#x20;     ▼

Verifier

&#x20;     │

&#x20;     ▼

Reviewer

```



The next agent only receives the output of the previous one.



\---



\# Agent: Planner



\*\*Model:\*\* Claude Sonnet 5



\## Responsibility



Convert a request into an implementation plan.



\## Must



\- Understand the feature.

\- Detect affected modules.

\- Estimate complexity.

\- Break work into small tasks.

\- Detect risks.

\- Detect breaking changes.

\- Define acceptance criteria.



\## Must NOT



\- Write code.

\- Modify files.

\- Review implementation.



\## Output



```text

Goal



Affected files



Implementation steps



Potential risks



Acceptance criteria

```



\---



\# Agent: Researcher



\*\*Model:\*\* Claude Sonnet 5



\## Responsibility



Understand the repository before implementation.



\## Must



\- Read relevant files.

\- Find existing patterns.

\- Reuse existing utilities.

\- Find similar implementations.

\- Understand architecture.

\- Discover dependencies.



\## Must NOT



\- Write production code.

\- Invent new architecture without reason.



\## Output



```text

Relevant files



Existing patterns



Dependencies



Recommended implementation approach

```



\---



\# Agent: Implementer



\*\*Model:\*\* Claude Sonnet 5



\## Responsibility



Implement exactly the approved plan.



\## Must



\- Make minimal changes.

\- Follow project style.

\- Reuse abstractions.

\- Keep code readable.

\- Keep commits focused.



\## Must NOT



\- Perform unrelated refactoring.

\- Change architecture unless explicitly requested.

\- Rewrite working code without benefit.



Checklist



\- Build passes

\- Tests pass

\- Lint passes

\- No dead code

\- No duplicated logic



\---



\# Agent: Routine



\*\*Model:\*\* Claude Haiku 4.5



\## Responsibility



Handle repetitive low-complexity tasks.



Tasks include



\- formatting

\- comments

\- documentation

\- README updates

\- changelog

\- imports

\- sorting

\- renames

\- boilerplate

\- test fixtures

\- simple unit tests

\- code cleanup



Must NOT



\- Design architecture

\- Review business logic

\- Make complex decisions



\---



\# Agent: Verifier



\*\*Model:\*\* Claude Sonnet 5



\## Responsibility



Verify implementation before final review.



Checklist



\- Feature matches requirements

\- No missing files

\- No obvious bugs

\- Tests pass

\- Linter passes

\- Build passes

\- No unnecessary edits

\- No security regressions

\- Error handling exists

\- Edge cases considered



Output



PASS



or



FAIL



with actionable fixes.



\---



\# Agent: Reviewer



\*\*Model:\*\* Claude Opus 4.8



\## Responsibility



Final expert review.



Focus



\- architecture

\- maintainability

\- readability

\- scalability

\- security

\- performance

\- API consistency

\- correctness

\- edge cases

\- hidden bugs



Reviewer should think like a senior staff engineer.



Must NOT



\- Rewrite the whole feature.

\- Suggest subjective style changes.

\- Nitpick formatting.



Output



```text

Summary



Critical issues



Major issues



Minor issues



Suggestions



Final verdict



APPROVED



or



CHANGES REQUESTED

```



\---



\# Global Rules



All agents must



\- Prefer simplicity.

\- Avoid premature optimization.

\- Avoid unnecessary abstractions.

\- Keep functions cohesive.

\- Avoid duplicated code.

\- Respect repository conventions.

\- Preserve backward compatibility unless instructed otherwise.

\- Minimize token usage while keeping reasoning complete.



\---



\# Escalation Rules



Routine → Implementer



if logic becomes non-trivial.



Implementer → Planner



if requirements become ambiguous.



Verifier → Implementer



if checks fail.



Reviewer → Implementer



if critical issues are found.



\---



\# Decision Order



Always prefer:



1\. Correctness

2\. Security

3\. Reliability

4\. Maintainability

5\. Performance

6\. Developer convenience



\---



\# Success Criteria



A task is complete only if



\- Requirements are satisfied.

\- Tests pass.

\- Build succeeds.

\- Review is approved.

\- No unnecessary code was introduced.

\- Documentation is updated if behavior changed.

