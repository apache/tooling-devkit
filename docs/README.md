# Design decisions

Why the kit is the way it is. Each record is one decision: what was decided, why, what it costs, and
what was not done instead. They are the kit's own and are not in `devkit.files`: a service has no use
for them, and the sync never copies them.

| Record | Decision |
| ------ | -------- |
| [0001](decisions/0001-one-source-with-synced-copies.md) | One repository is the source, and each service holds copies of its files |
| [0002](decisions/0002-names-and-devkit-conf.md) | The variables start with `DEVKIT_`; the names of a service come from `devkit.conf` |
| [0003](decisions/0003-the-sync.md) | A manifest, a lock and a check keep the copies as the kit has them |
| [0004](decisions/0004-the-guard-stands-down-only-in-its-container.md) | The guard stands down only where it lives at `/run/<service>` |
| [0005](decisions/0005-the-tests-stay-in-the-kit.md) | The kit's tests stay in the kit |
| [0006](decisions/0006-workflows-stay-in-the-services.md) | CI workflows stay in the services |
| [0007](decisions/0007-extension-points-are-data.md) | What a service adds is data it owns; the first is `scripts/local/verify.toml` |
| [0008](decisions/0008-the-kits-own-setup.md) | The kit's own Python setup is a Makefile, `pyproject.toml` and `uv.lock` |
| [0009](decisions/0009-seeding-and-generalising.md) | The kit is seeded from one repository and made general by applying it to others |
| [0010](decisions/0010-files-that-stand-alone.md) | A file of the kit refers to nothing that is not in the kit |

What is still open is in the tracking issue,
[apache/tooling-migration#50](https://github.com/apache/tooling-migration/issues/50).

## Adding a record

A new decision gets the next number and a file in `decisions/`, in the same pull request as the change
that makes it. A decision that is replaced is not deleted: its record says what replaced it, and the new
one says what it replaces. Keep to the headings below, and say only what was checked.

    # NNNN: the decision, as a sentence

    Status: accepted, and the pull request that made it so.

    ## Context        what was wrong or missing, and what we found out
    ## Decision       what is done now
    ## Consequences   what it costs, and what a repository has to do
    ## Not done       the alternatives, and why not
