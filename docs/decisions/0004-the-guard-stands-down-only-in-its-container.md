# 0004: The guard stands down only where it lives at `/run/<service>`

Status: accepted. Found by an adversarial pass before apache/tooling-devkit#1 was merged, and fixed in it.

## Context

The guard refuses commands that run the toolchain on the host. It has to stand down inside the dev
container, where running `uv` and `yarn` is the point. It first did so when `/run/<service>` existed, with
the service read from `devkit.conf`. But `devkit.conf` is the repository's file to write. A service of `.`,
`..`, `/` or `user` named a directory that exists on any host, and the guard allowed `uv run pytest`. So did
a duplicated key whose first line was `.`.

## Decision

- The guard stands down only if the directory two levels above the guard itself resolves to
  `/run/<service>`: that is where the container mounts the working tree, and nowhere else.
- It does so only for a service name that is one (0002). With no `devkit.conf`, or a name that is not valid,
  it stays on, which is the safe answer to "am I already inside".
- `checkout-id.sh` and `behaviour_pulls.py` apply the same rule to the name.

## Consequences

- Nothing a repository writes into its own files can switch the guard off.
- The guard test runs it from a copy in a directory of its own with the override removed, for each bad name
  and for no file. That it does stand down at `/run/<service>` is not tried: nothing makes a directory there.

## Not done

- **Testing for `/run/<service>` as a path.** That is what the first version did.
