# 0001: One repository is the source, and each service holds copies of its files

Status: accepted by the Tooling PMC on 2026-11-19 (D-18 in apache/tooling-migration, tracked in
apache/tooling-migration#50). First version: apache/tooling-devkit#1.

## Context

Each Tooling repository carried its own copy of the same developer files: the agent rules, the Bash
guard, the commands, the scripts and the CI workflows. The copies drifted in both directions. A fix to the
guard made in one repository reached another as a separate pull request, which was open for eleven days,
had fallen 116 commits behind and conflicted with its target before it was merged. By then there were three
versions of the guard, of 1,300 to 1,556 lines.

## Decision

`apache/tooling-devkit` holds the shared files. A service repository holds copies of them, at the paths it
already uses, so that a clone has the guard and the rules without any step. The copies are kept as the kit
has them (0003). A change to a copied file is a pull request in the kit, reviewed by the Tooling PMC.

## Consequences

- A fix is made once, and reaches each repository as a sync.
- A repository cannot change a shared file for itself. What differs on purpose has a place of its own:
  a value in `devkit.conf`, an extension point (0007), or an override with an issue and a date (0003).

## Not done

- **Git submodules.** A clone without `--recursive` has no guard and no rules.
- **A Claude Code plugin or skill only.** Each person has to install it, it cannot carry rules that are always
  loaded, and a guard that only some people have is not a guard. A skill for the work that agents do is
  planned in addition, not instead.
- **Templates with placeholders.** A filled-in copy is not the file that the kit tested.
