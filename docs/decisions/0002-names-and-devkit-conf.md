# 0002: The variables start with `DEVKIT_`; the names of a service come from `devkit.conf`

Status: accepted. Implemented in apache/tooling-devkit#1.

## Context

The scripts read variables such as `BAT_MEMORY` in tooling-agenda and `SR_MEMORY` in
tooling-secretary-records, and name images, volumes and containers after the service. About 430 lines of
the shared files held the prefix. If the prefix came from a config file, a shell script would need an
indirection (`eval "\${${PREFIX}_MEMORY:-}"`) in every one of them, and the guard refuses `eval`.

## Decision

- **One neutral prefix, `DEVKIT_`,** for every variable the kit's scripts read or set. The shared files
  are the same bytes in every repository.
- **`devkit.conf`** of a repository holds `DEVKIT_SERVICE` and `DEVKIT_REPOSITORY`, as `KEY=value` lines.
  Scripts read it with `sed` and never source it: the guard reads it too, and must not run a file of the
  repository it guards.
- **The service name** gives the image, volume, container and network names, and the working directory
  `/run/<service>`. It is lower case letters, digits, `-` and `_`, starting with a letter or a digit,
  because it ends up in names, `sed` patterns and a path.
- **Names that need no service are neutral:** temporary prefixes, lock and stamp files, labels.

## Consequences

- A repository renames the variables the kit reads or sets when it takes the kit, and the isx template sets
  `DEVKIT_ISOLATED=1` instead of its own name. The application's own variables stay.
- A repository's resource names change when it takes the kit: its volumes are named after `DEVKIT_SERVICE`.

## Not done

- **A prefix from the config.** The indirection above, in every script, and a test file that needs the
  prefix as a parameter.
- **Both names for a while.** An alias layer to keep, for a rename that happens once.
