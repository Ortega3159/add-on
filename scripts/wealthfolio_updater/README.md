# Wealthfolio updater

This directory contains the control-plane logic for the automated
Wealthfolio update pipeline used by this Home Assistant App repository.

The updater is intentionally conservative. Its job is to decide which
upstream version is eligible for testing and, later, publication. It does
not install updates into Home Assistant automatically.

## Current scope

The implementation in this directory currently covers the policy and
repository-integrity core only.

Implemented:

- strict upstream semantic-version parsing;
- strict Home Assistant wrapper-version parsing;
- conservative release selection;
- patch / minor / major update policy;
- exact manual approval semantics for review-required updates;
- prebuilt-image bootstrap planning;
- repository-state validation;
- strict updater-state JSON validation;
- byte-exact repository edits with CRLF preservation;
- stale Git base detection;
- unit tests for the above behavior.

Not implemented yet:

- GitHub release discovery;
- GHCR manifest and platform validation;
- Docker image builds;
- runtime compatibility tests;
- AppArmor compatibility tests;
- persistence and OLD -> NEW migration tests;
- exact image-artifact promotion;
- GHCR publication;
- repository publication;
- scheduled execution;
- issue/report deduplication.

Those capabilities are added in later work units and must not be assumed
to exist merely because their policy is described here.

## Architecture

The package is split by responsibility:

```text
wealthfolio_updater/
├── models.py
│   Domain types, enums, semantic versions and wrapper versions.
│
├── repository.py
│   Repository-state validation, updater-state parsing and byte-exact
│   file-editing primitives.
│
├── policy.py
│   Release classification, candidate selection, prebuilt bootstrap and
│   update-plan construction.
│
├── git_guard.py
│   Full-SHA validation and stale-base detection.
│
├── updater.py
│   Stable public facade re-exporting the supported package API.
│
└── tests/
    Unit tests for the policy and integrity core.
```

Future network discovery belongs in its own module rather than being
mixed into repository parsing or policy logic.

## Repository states

The updater recognizes two valid distribution modes.

### LOCAL_BUILD

The current repository does not declare an App `image:` and no updater
state file exists.

Conceptually:

```text
tracker/Dockerfile
  upstream version + immutable upstream digest

tracker/config.yml
  wrapper version
  no image

.github/wealthfolio-updater-state.json
  absent
```

This state requires the prebuilt-image bootstrap before any upstream
upgrade may be published.

### PREBUILT

The App declares the expected GHCR image and the updater state exists.

Conceptually:

```text
tracker/config.yml
  image = ghcr.io/ortega3159/wealthfolio-ha

.github/wealthfolio-updater-state.json
  schema
  image
  wrapper version
  published wrapper-image digest
```

The config and state must agree exactly.

Hybrid states such as an image without updater state, or updater state
without an image, are invalid and fail closed.

## Prebuilt bootstrap

The current migration path is intentionally separated from any upstream
Wealthfolio upgrade.

Current state:

```text
upstream 3.6.3
wrapper  3.6.3-4
LOCAL_BUILD
```

Bootstrap target:

```text
upstream 3.6.3
wrapper  3.6.3-5
PREBUILT
```

Even if a newer upstream version such as 3.8.0 is available, the
prebuilt bootstrap takes precedence.

This avoids combining:

1. a change in App distribution mechanism; and
2. an upstream application/database migration

in the same update.

## Release policy

For a repository already using PREBUILT distribution:

### Patch release

Example:

```text
3.8.2 -> 3.8.3
```

Policy:

```text
AUTO
```

This means the candidate may proceed automatically into the validation
gates. It does not mean the Home Assistant instance is updated
automatically.

### Minor release

Example:

```text
3.8.2 -> 3.9.0
```

Policy:

```text
REVIEW_REQUIRED
```

Publication requires an explicit approval matching the exact candidate
version.

For example:

```text
candidate        = 3.9.0
approved_version = 3.9.0
```

An approval for another version fails closed.

### Major release

Example:

```text
3.8.2 -> 4.0.0
```

Policy:

```text
BLOCK_MAJOR
```

An approval input does not bypass this policy.

## Candidate priority

The updater prefers the safest forward update class.

For example, if the current version is `3.8.2` and the available stable
versions include:

```text
3.8.3
3.9.0
4.0.0
```

the selected candidate is:

```text
3.8.3
```

The updater does not use approval input to skip that preferred patch and
jump directly to a later minor release.

## Wrapper versioning

Wrapper versions use:

```text
UPSTREAM-REVISION
```

For example:

```text
3.6.3-4
3.6.3-5
3.8.0-1
```

The revision is a positive integer.

When the upstream version changes, the wrapper revision starts again at
`1`.

The prebuilt bootstrap is different because the upstream version remains
the same, so the existing wrapper revision is incremented.

## Repository integrity

Repository-state validation requires, among other things:

- exactly one Wealthfolio upstream version ARG;
- exactly one Wealthfolio upstream digest ARG;
- a lowercase `sha256:` digest with 64 hexadecimal characters;
- exactly one upstream `FROM` using both pinned ARG values;
- wrapper upstream version matching the Dockerfile upstream version;
- architecture contract exactly `amd64` + `aarch64`;
- prebuilt image exactly
  `ghcr.io/ortega3159/wealthfolio-ha`;
- updater state schema exactly supported;
- no unknown schema-1 fields;
- no duplicate JSON object keys;
- exact agreement between config image/version and updater state.

The schema check intentionally distinguishes JSON booleans from integer
schema values.

## Byte-exact edits

`tracker/Dockerfile` and `tracker/config.yml` currently use CRLF line
endings.

Repository edits must not normalize the entire file.

The byte-editing primitives therefore:

- operate on bytes;
- require the search/anchor to occur exactly once;
- reject zero or multiple matches;
- preserve the detected line-ending convention;
- reject mixed line endings;
- preserve unrelated bytes.

This protects against accidental whole-file rewriting when the updater
later prepares publication changes.

## Plan versus validation versus publication

The pipeline is deliberately separated into three stages:

```text
PLAN
  Which candidate, if any, should be tested?
        |
        v
VALIDATION GATES
  Does that exact candidate pass compatibility and migration checks?
        |
        v
DECIDE / PUBLISH
  Is publication allowed for that exact tested candidate?
```

A PLAN candidate is not equivalent to a publishable or validated
candidate.

The runtime and publication gates are implemented in later work units.

## Stale-base protection

Planning and compatibility testing are tied to a full Git object ID.

Before publication, the future publisher must fetch the current target
branch and compare its full SHA against the SHA used during planning and
testing.

If they differ, publication aborts with a stale-base condition.

The updater never resolves that race by automatically rebasing, merging,
or force-pushing.

## Testing

The policy core uses only the Python standard library.

Run:

```bash
python3 -m unittest discover \
  -s scripts/wealthfolio_updater/tests \
  -v
```

The current WU-1 baseline contains 72 tests.

For structural changes, also verify module compilation and importability:

```bash
python3 -m py_compile \
  scripts/wealthfolio_updater/models.py \
  scripts/wealthfolio_updater/repository.py \
  scripts/wealthfolio_updater/policy.py \
  scripts/wealthfolio_updater/git_guard.py \
  scripts/wealthfolio_updater/updater.py
```

and:

```bash
python3 - <<'PY'
import scripts.wealthfolio_updater.models
import scripts.wealthfolio_updater.repository
import scripts.wealthfolio_updater.policy
import scripts.wealthfolio_updater.git_guard
import scripts.wealthfolio_updater.updater

print("all module imports = PASS")
PY
```

No unit test in this work unit requires Internet, Docker, GitHub or GHCR.

## Current development sequence

The intended sequence after this policy-core work is:

1. read-only upstream discovery;
2. audit-only GitHub Actions orchestration;
3. functional runtime harness;
4. AppArmor harness;
5. exact tested-artifact preservation;
6. integration of updater infrastructure;
7. GHCR namespace/public-access bootstrap;
8. prebuilt `3.6.3-5` bootstrap;
9. real pre-upgrade checkpoint;
10. reviewed Wealthfolio 3.8.0 update;
11. scheduled production updater.

Each stage must be independently verified before the next changes the
live App update path.
