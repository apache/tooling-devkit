# 0006: CI workflows stay in the services

Status: accepted. Implemented in apache/tooling-devkit#5 (merged 2026-11-22). The way to share them is open.

## Context

The four workflows of tooling-agenda were in the first version of the kit. Dependabot updates the pinned
actions in the `.github/workflows/` of each repository, so a copy would differ from the kit after every update,
and the drift check would fail. The workflows also hold what belongs to one service: the `subversion` and
LDAP packages and the minutes corpus, which a workflow cannot take from `devkit.conf`. The ASF self-hosted
runner labels are only tooling-agenda's, because it is the private repository; the public ones use hosted
runners.

## Decision

The workflows leave the kit and `devkit.files`. Each service keeps its own. The kit has a workflow of its
own, `.github/workflows/test.yml`, which runs `make test` (0008), and `.github/dependabot.yml` keeps its pins
current.

## Consequences

- The workflows can drift between services. Nothing checks that they do not.
- Only the runner labels are one repository's business. The dependabot drift and the service-specific
  steps are why they stay out, not the labels.

## Not done

- **Reusable workflows with inputs, pinned by commit id.** The likely way to share them, so that only the kit's
  copy is updated by dependabot and a service calls it. Open in the tracking issue.
