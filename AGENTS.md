# AGENTS.md

Notes for AI coding agents working in this repository, the devkit: the one source of the developer files that
every Apache Tooling repository shares. `AGENTS.shared.md` is the file the kit gives to services. It is not the
rules for working here, and this file does not import it.

[README.md](README.md) says what the kit is. [docs/design.md](docs/design.md) says why it is the way it is.

## Write little

- Say what is needed and stop: in code, comments, documents, pull request text and answers.
- A comment says what the code does and why. It does not tell how it got that way, and it does not cite an
  issue or a pull request of another repository.
- No emojis.

## Git

- Branch from `main`, and open the pull request against `main`. `main` takes squash and rebase merges and
  keeps a linear history.
- Rebase a branch onto `main`. Do not merge `main` into it. Push a rebased branch of your own with
  `--force-with-lease`.
- Commit subjects start with `feat:`, `fix:`, `chore:`, `docs:`, `test:` or `ci:`, and say what changed in
  one line.
- Stage the files you changed by name. No `git add -A`, and no bare `git stash`: the stash is shared by every
  worktree.
- Do not commit with `--no-verify`.

## The design document

Update `docs/design.md` in the same pull request when a change makes, changes or drops a design decision:
what was decided, why, what it costs, and what was not done instead. A decision that is replaced stays, with a
line that says what replaced it.

## Shared files

A file listed in `devkit.files` is copied to every repository, so it must work in one that is not
tooling-agenda: no service name, and no variable with a prefix other than `DEVKIT_`. It starts with the line
that names the kit. A new shared file goes in `devkit.files`, and a new file that stays here is declared in
`scripts/devkit-files.test.sh`; that test says what is missing. Run `make test` before you commit.
