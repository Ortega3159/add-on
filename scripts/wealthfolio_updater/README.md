# Wealthfolio updater

This directory contains the control-plane logic for the automated
Wealthfolio update pipeline used by this Home Assistant App repository.

The updater is intentionally conservative. Its job is to decide which
upstream version is eligible for testing and, later, publication. It does
not install updates into Home Assistant automatically.

## Current scope

The implementation in this directory currently covers the policy,
repository-integrity, read-only upstream-discovery and audit-only
orchestration layers.

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
- strict GitHub stable-release parsing;
- guarded GitHub release pagination;
- guarded read-only GitHub HTTP transport;
- strict GHCR Bearer-challenge validation;
- anonymous pull-only GHCR token acquisition;
- guarded GHCR manifest transport;
- raw OCI-index digest verification;
- strict multi-platform OCI-index inspection;
- exact `linux/amd64` and `linux/arm64` runtime-platform validation;
- fail-closed handling of OCI attestation descriptors;
- audit composition that keeps latest stable release, normal candidate,
  effective plan and inspected OCI target distinct;
- exact checkout-SHA and clean-worktree validation before repository or
  network audit work;
- deterministic machine-readable JSON and human-readable Markdown audit
  reports;
- a thin audit-only CLI with explicit technical-failure semantics;
- audit-only GitHub Actions orchestration with least-privilege permissions
  and immutable action pins;
- offline unit tests for all implemented behavior.

The read-only network path has also been smoke-tested against the real
upstream GitHub and GHCR endpoints. Those live checks are separate from
the offline unit-test suite.

Not implemented yet:

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
├── discovery.py
│   Strict GitHub release parsing and pagination.
│
├── github_http.py
│   Guarded read-only transport for the fixed upstream GitHub releases
│   endpoint.
│
├── oci.py
│   Raw OCI-index digest verification, platform validation and
│   attestation-descriptor inspection.
│
├── ghcr_http.py
│   Guarded anonymous pull-only GHCR challenge, token and manifest
│   transport.
│
├── audit.py
│   Pure audit composition: repository state, release selection, effective
│   plan and exact OCI target.
│
├── audit_execution.py
│   Checkout identity, clean-worktree and fixed-path repository guards,
│   followed by GitHub/GHCR audit execution.
│
├── audit_report.py
│   Explicit schema-1 JSON serialization and human-readable Markdown
│   rendering from one validated AuditResult.
│
├── audit_cli.py
│   Thin command-line boundary joining execution and reporting without
│   adding update or publication behavior.
│
├── updater.py
│   Stable public facade re-exporting the supported package API.
│
└── tests/
    Offline unit and workflow-contract tests for the implemented updater
    layers.
```

Network transport remains separated from repository parsing and policy
logic. The transport modules use fixed upstream destinations and
fail-closed validation rather than following arbitrary discovery or
authentication destinations supplied by remote responses.

## Audit-only GitHub Actions orchestration

WU-3 adds a read-only audit path. It does not build, publish, modify or
install anything.

The audit execution order is:

```text
exact event Git SHA
      |
      v
Gate 0: checkout / repository integrity
  - HEAD must match the expected full Git SHA
  - the Git worktree must be clean
  - repository state must validate
      |
      v
Gate 1: stable upstream discovery and planning
  - discover stable GitHub releases
  - preserve latest stable and normal candidate separately
  - construct the effective audit-only plan
      |
      v
Gate 2: exact upstream OCI identity
  - inspect only the OCI version selected by the effective plan
  - validate linux/amd64 and linux/arm64 runtime manifests
  - when inspecting the current upstream, require its OCI-index digest to
    match the repository pin exactly
      |
      v
AUDIT_ONLY result
```

Policy outcomes are valid audit conclusions rather than workflow failures.
Examples include `PREBUILT_BOOTSTRAP`, `NOOP`, `CANDIDATE_AUTO`,
`CANDIDATE_REVIEW_REQUIRED` and `POLICY_BLOCK_MAJOR`.

Technical or integrity failures remain fail closed. Examples include a stale
or malformed Git SHA, a dirty checkout, invalid repository state, malformed
GitHub/GHCR responses, no stable releases, invalid OCI metadata or a current
OCI digest that does not match the repository pin.

The CLI executes the audit once and derives both reports from the same
validated result:

- compact schema-1 JSON on standard output;
- Markdown written to the requested summary path.

The GitHub Actions workflow is
`.github/workflows/wealthfolio-updater-audit.yml`.

It currently:

- grants only `contents: read`;
- checks out the exact `${{ github.sha }}`;
- uses `fetch-depth: 1`;
- disables persisted checkout credentials;
- pins `actions/checkout` and `actions/setup-python` to full commit SHAs;
- uses Python `3.14.2`;
- runs the complete offline unit-test suite before the live audit;
- writes the human-readable result to the GitHub Step Summary.

The branch-specific `push` trigger for `feat/wealthfolio-updater` is a
temporary bootstrap mechanism for the first remote workflow validation.
`workflow_dispatch` is also declared, but manual dispatch becomes useful
once the workflow exists on the default branch. The branch-specific
bootstrap trigger must be removed or reevaluated when WU-3 is integrated.

WU-3 does not provide:

- Docker builds;
- image publication;
- repository mutation;
- approval input;
- scheduled execution;
- access to Home Assistant OS, Tailscale, the home network or real financial
  data.

The workflow and all WU-3 code are currently validated locally. The first
real GitHub Actions run remains pending until this work unit is committed
and pushed.

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

The updater implementation currently uses only the Python standard
library.

Run:

```bash
python3 -m unittest discover \
  -s scripts/wealthfolio_updater/tests \
  -v
```

The current WU-3 baseline contains 200 offline unit tests.

For structural changes, also verify module compilation and importability:

```bash
python3 -m py_compile \
  scripts/wealthfolio_updater/models.py \
  scripts/wealthfolio_updater/repository.py \
  scripts/wealthfolio_updater/policy.py \
  scripts/wealthfolio_updater/git_guard.py \
  scripts/wealthfolio_updater/discovery.py \
  scripts/wealthfolio_updater/github_http.py \
  scripts/wealthfolio_updater/oci.py \
  scripts/wealthfolio_updater/ghcr_http.py \
  scripts/wealthfolio_updater/audit.py \
  scripts/wealthfolio_updater/audit_execution.py \
  scripts/wealthfolio_updater/audit_report.py \
  scripts/wealthfolio_updater/audit_cli.py \
  scripts/wealthfolio_updater/updater.py
```

and:

```bash
python3 - <<'CHECK'
import scripts.wealthfolio_updater.models
import scripts.wealthfolio_updater.repository
import scripts.wealthfolio_updater.policy
import scripts.wealthfolio_updater.git_guard
import scripts.wealthfolio_updater.discovery
import scripts.wealthfolio_updater.github_http
import scripts.wealthfolio_updater.oci
import scripts.wealthfolio_updater.ghcr_http
import scripts.wealthfolio_updater.audit
import scripts.wealthfolio_updater.audit_execution
import scripts.wealthfolio_updater.audit_report
import scripts.wealthfolio_updater.audit_cli
import scripts.wealthfolio_updater.updater

print("all module imports = PASS")
CHECK
```

The unit-test suite requires no Internet, Docker, GitHub or GHCR access.

Separate live smoke checks have verified the read-only network path
against the real upstream services, including:

- stable GitHub release discovery;
- the current repository upstream `3.6.3`;
- the review-required upstream candidate `3.8.0`;
- exact GHCR OCI-index digest matching;
- exact `linux/amd64` and `linux/arm64` manifest discovery.

Live smoke checks are evidence for the transport contract; they are not
a substitute for the offline unit-test suite.

The WU-3 GitHub Actions orchestration has not yet had its first remote run.
That validation occurs only after the reviewed WU-3 commit is pushed.

## Current development sequence

The policy core, read-only upstream discovery and local implementation of
the audit-only GitHub Actions orchestration are complete.

The remaining intended sequence is:

1. first remote WU-3 workflow validation;
2. functional runtime harness;
3. AppArmor harness;
4. exact tested-artifact preservation;
5. integration of updater infrastructure;
6. GHCR namespace/public-access bootstrap;
7. prebuilt `3.6.3-5` bootstrap;
8. real pre-upgrade checkpoint;
9. reviewed Wealthfolio 3.8.0 update;
10. scheduled production updater.

Each stage must be independently verified before the next changes the
live App update path.
