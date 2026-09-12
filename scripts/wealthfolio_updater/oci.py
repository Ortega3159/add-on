from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass


OCI_IMAGE_INDEX_MEDIA_TYPE = (
    "application/vnd.oci.image.index.v1+json"
)

OCI_IMAGE_MANIFEST_MEDIA_TYPE = (
    "application/vnd.oci.image.manifest.v1+json"
)

_DIGEST_RE = re.compile(
    r"sha256:[0-9a-f]{64}"
)

_ATTESTATION_TYPE_KEY = (
    "vnd.docker.reference.type"
)

_ATTESTATION_DIGEST_KEY = (
    "vnd.docker.reference.digest"
)

_ATTESTATION_TYPE = "attestation-manifest"


@dataclass(frozen=True)
class OciIndexInspection:
    index_digest: str
    amd64_digest: str
    arm64_digest: str
    attestation_count: int


def _reject_duplicate_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}

    for key, value in pairs:
        if key in result:
            raise ValueError(
                f"duplicate JSON object key: {key!r}"
            )

        result[key] = value

    return result


def _validate_digest(
    value: object,
    *,
    label: str,
) -> str:
    if type(value) is not str:
        raise ValueError(
            f"{label} must be a string"
        )

    if _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(
            f"{label} must be a canonical sha256 digest"
        )

    return value


def _parse_index_json(
    body: bytes,
) -> dict[str, object]:
    if type(body) is not bytes:
        raise TypeError("body must be bytes")

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "OCI index body is not valid UTF-8"
        ) from exc

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "OCI index body is not valid JSON"
        ) from exc

    if not isinstance(decoded, dict):
        raise ValueError(
            "OCI index must be a JSON object"
        )

    return decoded


def inspect_oci_index(
    *,
    body: bytes,
    content_type: str,
    content_digest: str,
) -> OciIndexInspection:
    if type(content_type) is not str:
        raise ValueError(
            "Content-Type must be text"
        )

    if content_type != OCI_IMAGE_INDEX_MEDIA_TYPE:
        raise ValueError(
            "unsupported OCI index Content-Type"
        )

    expected_digest = _validate_digest(
        content_digest,
        label="Docker-Content-Digest",
    )

    if type(body) is not bytes:
        raise TypeError("body must be bytes")

    calculated_digest = (
        "sha256:"
        + hashlib.sha256(body).hexdigest()
    )

    if expected_digest != calculated_digest:
        raise ValueError(
            "Docker-Content-Digest does not match raw body"
        )

    index = _parse_index_json(body)

    schema_version = index.get("schemaVersion")

    if (
        type(schema_version) is not int
        or schema_version != 2
    ):
        raise ValueError(
            "OCI index schemaVersion must be integer 2"
        )

    media_type = index.get("mediaType")

    if media_type != OCI_IMAGE_INDEX_MEDIA_TYPE:
        raise ValueError(
            "OCI index mediaType does not match expected type"
        )

    manifests = index.get("manifests")

    if not isinstance(manifests, list):
        raise ValueError(
            "OCI index manifests must be an array"
        )

    runtime_digests: dict[str, str] = {}
    attestation_references: list[str] = []
    seen_descriptor_digests: set[str] = set()

    for position, descriptor in enumerate(
        manifests,
        start=1,
    ):
        if not isinstance(descriptor, dict):
            raise ValueError(
                f"descriptor {position} must be an object"
            )

        descriptor_media_type = descriptor.get(
            "mediaType"
        )

        if (
            descriptor_media_type
            != OCI_IMAGE_MANIFEST_MEDIA_TYPE
        ):
            raise ValueError(
                f"descriptor {position} has unsupported mediaType"
            )

        digest = _validate_digest(
            descriptor.get("digest"),
            label=f"descriptor {position} digest",
        )

        if digest in seen_descriptor_digests:
            raise ValueError(
                f"duplicate descriptor digest: {digest}"
            )

        seen_descriptor_digests.add(digest)

        size = descriptor.get("size")

        if type(size) is not int or size <= 0:
            raise ValueError(
                f"descriptor {position} has invalid size"
            )

        platform = descriptor.get("platform")

        if not isinstance(platform, dict):
            raise ValueError(
                f"descriptor {position} platform must be an object"
            )

        operating_system = platform.get("os")
        architecture = platform.get("architecture")

        if (
            type(operating_system) is not str
            or type(architecture) is not str
        ):
            raise ValueError(
                f"descriptor {position} has invalid platform"
            )

        if operating_system == "linux":
            if architecture not in (
                "amd64",
                "arm64",
            ):
                raise ValueError(
                    "unexpected runtime platform: "
                    f"{operating_system}/{architecture}"
                )

            if architecture in runtime_digests:
                raise ValueError(
                    "duplicate runtime platform: "
                    f"linux/{architecture}"
                )

            runtime_digests[architecture] = digest
            continue

        if (
            operating_system == "unknown"
            and architecture == "unknown"
        ):
            annotations = descriptor.get(
                "annotations"
            )

            if not isinstance(annotations, dict):
                raise ValueError(
                    "unknown/unknown descriptor must be "
                    "an annotated attestation"
                )

            if (
                annotations.get(
                    _ATTESTATION_TYPE_KEY
                )
                != _ATTESTATION_TYPE
            ):
                raise ValueError(
                    "unknown/unknown descriptor is not "
                    "an attestation-manifest"
                )

            reference_digest = _validate_digest(
                annotations.get(
                    _ATTESTATION_DIGEST_KEY
                ),
                label=(
                    "attestation reference digest"
                ),
            )

            attestation_references.append(
                reference_digest
            )
            continue

        raise ValueError(
            "unexpected descriptor platform: "
            f"{operating_system}/{architecture}"
        )

    required_architectures = {
        "amd64",
        "arm64",
    }

    if set(runtime_digests) != required_architectures:
        missing = sorted(
            required_architectures
            - set(runtime_digests)
        )

        raise ValueError(
            "missing required runtime platforms: "
            + ", ".join(
                f"linux/{architecture}"
                for architecture in missing
            )
        )

    allowed_attestation_targets = set(
        runtime_digests.values()
    )

    for reference_digest in attestation_references:
        if (
            reference_digest
            not in allowed_attestation_targets
        ):
            raise ValueError(
                "attestation does not reference "
                "a runtime manifest"
            )

    return OciIndexInspection(
        index_digest=calculated_digest,
        amd64_digest=runtime_digests["amd64"],
        arm64_digest=runtime_digests["arm64"],
        attestation_count=len(
            attestation_references
        ),
    )
