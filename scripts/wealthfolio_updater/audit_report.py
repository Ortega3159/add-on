from __future__ import annotations

import json

from .audit import AuditResult


_REPORT_SCHEMA = 1


def _optional_text(value) -> str | None:
    if value is None:
        return None

    return str(value)


def _markdown_optional(value) -> str:
    if value is None:
        return "none"

    return str(value)


def audit_result_to_dict(
    result: AuditResult,
) -> dict[str, object]:
    repository = result.repository
    candidate = result.candidate
    plan = result.plan
    oci = result.oci
    inspection = oci.inspection

    return {
        "schema": _REPORT_SCHEMA,
        "disposition": result.disposition,
        "audited_git_sha": result.audited_git_sha,
        "repository": {
            "upstream_version": str(
                repository.upstream_version
            ),
            "upstream_digest": (
                repository.upstream_digest
            ),
            "wrapper_version": str(
                repository.wrapper_version
            ),
            "distribution_mode": (
                repository.distribution_mode.value
            ),
            "architectures": sorted(
                repository.architectures
            ),
            "image": repository.image,
            "published_digest": (
                repository.published_digest
            ),
        },
        "discovery": {
            "stable_release_count": (
                result.stable_release_count
            ),
            "latest_stable": str(
                result.latest_stable
            ),
            "candidate": {
                "version": _optional_text(
                    candidate.version
                ),
                "policy": candidate.policy.value,
            },
        },
        "plan": {
            "state": plan.state.value,
            "target_upstream": _optional_text(
                plan.target_upstream
            ),
            "target_wrapper": _optional_text(
                plan.target_wrapper
            ),
            "policy": (
                plan.policy.value
                if plan.policy is not None
                else None
            ),
        },
        "oci": {
            "version": str(oci.version),
            "expected_index_digest": (
                oci.expected_index_digest
            ),
            "index_digest": (
                inspection.index_digest
            ),
            "amd64_digest": (
                inspection.amd64_digest
            ),
            "arm64_digest": (
                inspection.arm64_digest
            ),
            "attestation_count": (
                inspection.attestation_count
            ),
        },
    }


def render_audit_json(
    result: AuditResult,
) -> str:
    return (
        json.dumps(
            audit_result_to_dict(result),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    )


def render_audit_markdown(
    result: AuditResult,
) -> str:
    payload = audit_result_to_dict(result)

    repository = payload["repository"]
    discovery = payload["discovery"]
    candidate = discovery["candidate"]
    plan = payload["plan"]
    oci = payload["oci"]

    lines = [
        "# Wealthfolio updater audit",
        "",
        f"- Disposition: `{payload['disposition']}`",
        f"- Audited Git SHA: `{payload['audited_git_sha']}`",
        "",
        "## Repository",
        "",
        (
            "- Upstream: "
            f"`{repository['upstream_version']}`"
        ),
        (
            "- Upstream digest: "
            f"`{repository['upstream_digest']}`"
        ),
        (
            "- Wrapper: "
            f"`{repository['wrapper_version']}`"
        ),
        (
            "- Distribution mode: "
            f"`{repository['distribution_mode']}`"
        ),
        (
            "- Image: "
            f"`{_markdown_optional(repository['image'])}`"
        ),
        (
            "- Published digest: "
            f"`{_markdown_optional(repository['published_digest'])}`"
        ),
        (
            "- Architectures: "
            + ", ".join(
                f"`{architecture}`"
                for architecture
                in repository["architectures"]
            )
        ),
        "",
        "## Discovery",
        "",
        (
            "- Stable release count: "
            f"`{discovery['stable_release_count']}`"
        ),
        (
            "- Latest stable: "
            f"`{discovery['latest_stable']}`"
        ),
        (
            "- Normal candidate: "
            f"`{_markdown_optional(candidate['version'])}`"
        ),
        (
            "- Candidate policy: "
            f"`{candidate['policy']}`"
        ),
        "",
        "## Effective plan",
        "",
        f"- State: `{plan['state']}`",
        (
            "- Target upstream: "
            f"`{_markdown_optional(plan['target_upstream'])}`"
        ),
        (
            "- Target wrapper: "
            f"`{_markdown_optional(plan['target_wrapper'])}`"
        ),
        (
            "- Policy: "
            f"`{_markdown_optional(plan['policy'])}`"
        ),
        "",
        "## OCI identity",
        "",
        f"- Inspected version: `{oci['version']}`",
        (
            "- Expected index digest: "
            f"`{_markdown_optional(oci['expected_index_digest'])}`"
        ),
        (
            "- OCI index digest: "
            f"`{oci['index_digest']}`"
        ),
        (
            "- linux/amd64 digest: "
            f"`{oci['amd64_digest']}`"
        ),
        (
            "- linux/arm64 digest: "
            f"`{oci['arm64_digest']}`"
        ),
        (
            "- Attestation count: "
            f"`{oci['attestation_count']}`"
        ),
        "",
    ]

    return "\n".join(lines)
