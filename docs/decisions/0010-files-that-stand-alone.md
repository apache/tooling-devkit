# 0010: A file of the kit refers to nothing that is not in the kit

Status: accepted. Implemented in apache/tooling-devkit#5.

## Context

The files came from tooling-agenda with comments that cited its issues and pull requests, dates, the names
of people, and the story of how a rule came to be. In the kit that context is gone: a reference to
`#729` of another repository is a number nobody can follow, and a comment that says "this used to be a bare
`except`" describes a version nobody can reach.

## Decision

- A comment says what the code does and why, and warns of what an edit could bring back. It does not tell
  how it got that way.
- A file does not cite an issue or a pull request of another repository, a date of an incident, or a person.
  A reference to the tracking issue of the kit, or to a record in this folder, is fine.
- A measurement that explains a constant stays, with what it was measured on.
- Examples use neutral names: `tooling-service#12`, `@<github-username>`.

## Consequences

- 49 references were rewritten. Outside comments, only docstrings in five Python files and two sentences that
  `pr-review.sh` prints changed, which was checked line by line.
- A file ported from a service is cleaned the same way before it comes in.

## Not done

- **Keeping the references,** as a trail back to the services. The history is in the services.
