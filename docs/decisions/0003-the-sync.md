# 0003: A manifest, a lock and a check keep the copies as the kit has them

Status: accepted. Implemented in apache/tooling-devkit#4.

## Context

Copying files without a record of where they came from, or a way to tell that a copy was edited, is how
the drift started.

## Decision

- **`devkit.files`** in the kit lists what a service may take: a path, or `source destination`. What the kit
  holds and does not list is the kit's own.
- **`devkit.lock`** in a service holds the kit commit it took, and `override <path> <issue> until <YYYY-MM-DD>`
  lines for a copy that differs on purpose. The sync rewrites only the `commit` line.
- **`scripts/devkit-sync.sh <ref>`** copies the listed files at that commit and writes the commit to the lock.
  **`--check`** compares each file with the kit at the locked commit, prints each override, and fails on
  drift, a missing file, an override past its day, and a lock that is not usable. It is one script.
- **`DEVKIT_SKIP`** in `devkit.conf` names what a repository keeps as its own. It lists what is left out,
  not what is taken, so a file the kit adds reaches every repository by default.
- **The first line of a copy says where to change it.** It is in the kit's own file, so a copy stays
  byte-identical. A file that cannot carry a comment (`.claude/settings.json`, the license template) has
  none, and the check covers it all the same.
- **Files are compared with `git diff --no-index`,** which also sees a lost executable bit. `cmp` is not in every
  container, and `git` is needed anyway.
- **The check reads the real kit at the locked commit, not hashes in the lock.** A hash edited together with
  its file would hide the drift.

## Consequences

- The first copy of `devkit-sync.sh` is made by hand, and `<ref>` is a branch, a tag or a full commit id:
  git does not fetch an abbreviated one.
- A kit that lists a path the sync must not write (absolute, upward, inside `.git`, or the service's own
  `devkit.conf` or `devkit.lock`) is refused before anything is copied.
- The check is not yet run in any repository's CI, and nothing opens a sync pull request yet: both need a
  repository that has taken the kit first.

## Not done

- **A `files:` list of what a repository takes.** A new kit file would reach nobody until each repository
  added it. And `devkit.conf` is `KEY=value`, which holds no list.
- **A separate drift-check script.** One script is one file to take, and to change.
