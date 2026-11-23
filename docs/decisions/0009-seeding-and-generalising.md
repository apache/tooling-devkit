# 0009: The kit is seeded from one repository and made general by applying it to others

Status: accepted. Done for the first version in apache/tooling-devkit#1, and again in apache/tooling-devkit#3 and apache/tooling-devkit#6.

## Context

Four repositories held the shared files, and the proposal said to take the best version of each. They did not
all differ in the same direction, and tooling-agenda was the one that kept moving.

## Decision

- **Seed from the repository that has the latest version,** tooling-agenda. The first version is built in steps
  so that a review can follow them: the files as they were, the rename to `DEVKIT_` (0002), and the names
  taken from `devkit.conf`, then the documents. A change that lands in tooling-agenda later comes in as its own pull request.
- **Find what is not general by applying the kit to another repository** in a scratch copy and running its tests,
  before any repository is changed. That found, in tooling-secretary-records, the tests that assumed a service
  called `devkit` (0005), and three files where its version was the more general one: `quality_meters.py`
  tolerates a tree without the files a meter reads, `apt-install.sh` checks that the metadata answer is a
  region, and `production_import.py` imports a type under `TYPE_CHECKING`. They were taken into the kit.
- **Show a new test failing first.** A test that has only ever passed has not been shown to test anything.

## Consequences

- A change to a copied file in a service is lost at the next sync unless it was made in the kit.
- A repository's own tests of the kit's scripts stop being copies (0005), and are not run against the
  synced scripts.

## Not done

- **A merge of all four repositories before anything was published.** It would have been one large review of
  files whose differences were mostly names.
