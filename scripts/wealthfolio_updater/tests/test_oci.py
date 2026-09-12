import hashlib
import json
import unittest

from scripts.wealthfolio_updater.oci import (
    OCI_IMAGE_INDEX_MEDIA_TYPE,
    OCI_IMAGE_MANIFEST_MEDIA_TYPE,
    inspect_oci_index,
)


AMD64_DIGEST = (
    "sha256:"
    "8477ea3bb4cb37482ba6c97a337fbffb"
    "0cb967ad0bddac5bbc79ae33e79026d1"
)

ARM64_DIGEST = (
    "sha256:"
    "02174ee0356536fdebb713ef28585a15"
    "9f973c02f78f0bd033e8f1243055a80c"
)


def make_index(
    *,
    descriptors=None,
):
    if descriptors is None:
        descriptors = [
            {
                "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
                "digest": AMD64_DIGEST,
                "size": 1243,
                "platform": {
                    "os": "linux",
                    "architecture": "amd64",
                },
            },
            {
                "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
                "digest": ARM64_DIGEST,
                "size": 1243,
                "platform": {
                    "os": "linux",
                    "architecture": "arm64",
                },
            },
            {
                "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
                "digest": (
                    "sha256:"
                    "1236eda3aeae42fefc80e827477d7370"
                    "d07167e28d85985dda8f2cf11fdfc860"
                ),
                "size": 838,
                "platform": {
                    "os": "unknown",
                    "architecture": "unknown",
                },
                "annotations": {
                    "vnd.docker.reference.digest": AMD64_DIGEST,
                    "vnd.docker.reference.type":
                        "attestation-manifest",
                },
            },
            {
                "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
                "digest": (
                    "sha256:"
                    "7247ee11ad1cd43bb06b1dd878d77ab"
                    "3220957ab9bf78f944e01edd6d98db90a"
                ),
                "size": 838,
                "platform": {
                    "os": "unknown",
                    "architecture": "unknown",
                },
                "annotations": {
                    "vnd.docker.reference.digest": ARM64_DIGEST,
                    "vnd.docker.reference.type":
                        "attestation-manifest",
                },
            },
        ]

    return json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": OCI_IMAGE_INDEX_MEDIA_TYPE,
            "manifests": descriptors,
        },
        separators=(",", ":"),
    ).encode("utf-8")


def digest_of(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


class OciIndexInspectionTests(unittest.TestCase):
    def test_accepts_current_multiarch_shape_with_attestations(self):
        body = make_index()

        inspection = inspect_oci_index(
            body=body,
            content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
            content_digest=digest_of(body),
        )

        self.assertEqual(
            inspection.index_digest,
            digest_of(body),
        )
        self.assertEqual(
            inspection.amd64_digest,
            AMD64_DIGEST,
        )
        self.assertEqual(
            inspection.arm64_digest,
            ARM64_DIGEST,
        )
        self.assertEqual(
            inspection.attestation_count,
            2,
        )

    def test_header_digest_must_match_raw_body(self):
        body = make_index()

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest="sha256:" + "0" * 64,
            )

    def test_content_type_must_be_supported_index_type(self):
        body = make_index()

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type="application/json",
                content_digest=digest_of(body),
            )

    def test_schema_version_must_be_integer_two(self):
        for schema in (True, 1, 3, "2"):
            with self.subTest(schema=schema):
                body = json.dumps(
                    {
                        "schemaVersion": schema,
                        "mediaType": OCI_IMAGE_INDEX_MEDIA_TYPE,
                        "manifests": [],
                    }
                ).encode()

                with self.assertRaises(ValueError):
                    inspect_oci_index(
                        body=body,
                        content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                        content_digest=digest_of(body),
                    )

    def test_requires_linux_amd64(self):
        descriptors = json.loads(
            make_index().decode()
        )["manifests"]

        descriptors = [
            descriptor
            for descriptor in descriptors
            if descriptor.get("platform", {}).get(
                "architecture"
            ) != "amd64"
        ]

        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_requires_linux_arm64(self):
        descriptors = json.loads(
            make_index().decode()
        )["manifests"]

        descriptors = [
            descriptor
            for descriptor in descriptors
            if descriptor.get("platform", {}).get(
                "architecture"
            ) != "arm64"
        ]

        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_duplicate_supported_platform_is_rejected(self):
        descriptors = json.loads(
            make_index().decode()
        )["manifests"]

        descriptors.append(dict(descriptors[0]))

        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_unexpected_runtime_platform_is_rejected(self):
        descriptors = json.loads(
            make_index().decode()
        )["manifests"]

        descriptors.append(
            {
                "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
                "digest": "sha256:" + "a" * 64,
                "size": 1000,
                "platform": {
                    "os": "linux",
                    "architecture": "arm",
                },
            }
        )

        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_unknown_unknown_requires_attestation_annotation(self):
        descriptors = json.loads(
            make_index().decode()
        )["manifests"]

        descriptors[2].pop("annotations")

        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_attestation_must_reference_runtime_manifest(self):
        descriptors = json.loads(
            make_index().decode()
        )["manifests"]

        descriptors[2]["annotations"][
            "vnd.docker.reference.digest"
        ] = "sha256:" + "f" * 64

        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_duplicate_json_keys_are_rejected(self):
        body = (
            b'{"schemaVersion":2,'
            b'"schemaVersion":2,'
            b'"mediaType":"'
            + OCI_IMAGE_INDEX_MEDIA_TYPE.encode()
            + b'","manifests":[]}'
        )

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )



class OciIndexHardeningTests(unittest.TestCase):
    def test_invalid_descriptor_digest_is_rejected(self):
        descriptors = json.loads(
            make_index().decode()
        )["manifests"]

        descriptors[0]["digest"] = "sha256:abc"

        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_boolean_descriptor_size_is_rejected(self):
        descriptors = json.loads(
            make_index().decode()
        )["manifests"]

        descriptors[0]["size"] = True

        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_unexpected_operating_system_is_rejected(self):
        descriptors = json.loads(
            make_index().decode()
        )["manifests"]

        descriptors[0]["platform"]["os"] = "windows"

        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_malformed_manifest_shapes_are_rejected(self):
        bodies = (
            json.dumps(
                {
                    "schemaVersion": 2,
                    "mediaType": OCI_IMAGE_INDEX_MEDIA_TYPE,
                    "manifests": {},
                }
            ).encode(),
            make_index(
                descriptors=["not-an-object"]
            ),
        )

        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    inspect_oci_index(
                        body=body,
                        content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                        content_digest=digest_of(body),
                    )

    def test_invalid_utf8_and_json_are_rejected(self):
        bodies = (
            b"\xff",
            b"{",
        )

        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    inspect_oci_index(
                        body=body,
                        content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                        content_digest=digest_of(body),
                    )

    def test_attestations_are_optional(self):
        descriptors = json.loads(
            make_index().decode()
        )["manifests"]

        descriptors = [
            descriptor
            for descriptor in descriptors
            if descriptor["platform"]["os"] == "linux"
        ]

        body = make_index(descriptors=descriptors)

        inspection = inspect_oci_index(
            body=body,
            content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
            content_digest=digest_of(body),
        )

        self.assertEqual(
            inspection.amd64_digest,
            AMD64_DIGEST,
        )
        self.assertEqual(
            inspection.arm64_digest,
            ARM64_DIGEST,
        )
        self.assertEqual(
            inspection.attestation_count,
            0,
        )

    def test_duplicate_descriptor_digest_is_rejected(self):
        descriptors = json.loads(
            make_index().decode()
        )["manifests"]

        descriptors[2]["digest"] = AMD64_DIGEST

        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_body_media_type_must_match_oci_index(self):
        body = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": "application/json",
                "manifests": [],
            }
        ).encode()

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )



class OciIndexHardeningTests(unittest.TestCase):
    def test_invalid_descriptor_digest_is_rejected(self):
        descriptors = json.loads(make_index().decode())["manifests"]
        descriptors[0]["digest"] = "sha256:abc"
        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_boolean_descriptor_size_is_rejected(self):
        descriptors = json.loads(make_index().decode())["manifests"]
        descriptors[0]["size"] = True
        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_unexpected_operating_system_is_rejected(self):
        descriptors = json.loads(make_index().decode())["manifests"]
        descriptors[0]["platform"]["os"] = "windows"
        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_manifests_must_be_array(self):
        body = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": OCI_IMAGE_INDEX_MEDIA_TYPE,
                "manifests": {},
            }
        ).encode()

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_descriptor_must_be_object(self):
        body = make_index(descriptors=["not-an-object"])

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )

    def test_invalid_utf8_and_json_are_rejected(self):
        for body in (b"\xff", b"{"):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    inspect_oci_index(
                        body=body,
                        content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                        content_digest=digest_of(body),
                    )

    def test_attestations_are_optional(self):
        descriptors = json.loads(make_index().decode())["manifests"]
        descriptors = [
            descriptor
            for descriptor in descriptors
            if descriptor["platform"]["os"] == "linux"
        ]

        body = make_index(descriptors=descriptors)

        inspection = inspect_oci_index(
            body=body,
            content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
            content_digest=digest_of(body),
        )

        self.assertEqual(inspection.amd64_digest, AMD64_DIGEST)
        self.assertEqual(inspection.arm64_digest, ARM64_DIGEST)
        self.assertEqual(inspection.attestation_count, 0)

    def test_duplicate_descriptor_digest_is_rejected(self):
        descriptors = json.loads(make_index().decode())["manifests"]
        descriptors[2]["digest"] = AMD64_DIGEST
        body = make_index(descriptors=descriptors)

        with self.assertRaises(ValueError):
            inspect_oci_index(
                body=body,
                content_type=OCI_IMAGE_INDEX_MEDIA_TYPE,
                content_digest=digest_of(body),
            )


if __name__ == "__main__":
    unittest.main()
