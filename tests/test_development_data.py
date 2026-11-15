"""W3-00 development boundary tests; all generated records are synthetic."""

import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from egis_soc import development_data
from egis_soc.development_data import from_synthetic_fixture, load_private_pds01_group
from egis_soc.integrity import canonical_bytes
from egis_soc.pds01_provisional import VERSION, _id, jsonl
from egis_soc.public_pilot_intake import _canonical
from egis_soc.schemas import EvidenceEvent, EvidenceProvenance, IncidentBundle


class DevelopmentDataTests(unittest.TestCase):
    def _private_fixture(self, root: Path, *, group: str = "S07", event_change=None,
                         bundle_change=None, annotation_change=None):
        folder = root / group
        folder.mkdir()
        source_ref = "SYN-REF-1"
        evidence_id = _id(group, source_ref)
        event = {
            "version": VERSION, "evidence_id": evidence_id,
            "incident_id": f"PDS01-DEV-{group}-v1", "tenant_id": "UNKNOWN",
            "source_ref": source_ref, "source_key": f"{group}-01",
            "repository_path": "synthetic/path.xml", "source_dataset": "PDS-01",
            "artifact_sha256": "a" * 64, "raw_sha256": "b" * 64,
            "raw_message_ref": f"pds01-provisional:{group}-01:1",
            "timestamp_utc": "2026-01-01T00:00:01+00:00",
            "timestamp_original": "2026-01-01T00:00:01Z",
            "event_data": {"CommandLine": "[REDACTED]", "Image": "synthetic.exe"},
            "membership_status": "AI_PROPOSED_INCLUDE_UNREVIEWED",
        }
        event.update(event_change or {})
        bundle = {
            "version": VERSION, "status": "UNREVIEWED_DEVELOPMENT",
            "scenario": group, "incident_id": f"PDS01-DEV-{group}-v1",
            "tenant_id": "UNKNOWN", "environment_id": "PDS01_PRIVATE_DEVELOPMENT",
            "source_dataset": "PDS-01", "partition": "train_designated_grouped",
            "lineage_group": "PDS01_ALL", "upstream_original_run_id": "UNKNOWN",
            "annotation_status": "AI_PROPOSED_UNREVIEWED_NOT_GOLD",
            "boundary_status": "AI_PROPOSED_NOT_OWNER_REVIEWED",
            "evidence_ids": [evidence_id],
        }
        bundle.update(bundle_change or {})
        annotation = {
            "incident_id": bundle["incident_id"], "tenant_id": "UNKNOWN",
            "evidence_ids": [evidence_id], "source_ref": source_ref,
            "annotation_source": "AI_PROPOSED", "gold_status": "NOT_GOLD",
            "human_label": "UNREVIEWED", "human_status": "UNREVIEWED",
        }
        annotation.update(annotation_change or {})
        (folder / "bundle.json").write_bytes(canonical_bytes(bundle))
        (folder / "events.jsonl").write_bytes(jsonl([event]))
        for name in ("pairs.jsonl", "facts.jsonl"):
            (folder / name).write_bytes(jsonl([annotation]))
        hashes = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                  for name in ("bundle.json", "events.jsonl", "pairs.jsonl", "facts.jsonl")}
        manifest = {
            "version": VERSION, "status": "UNREVIEWED_DEVELOPMENT",
            "accepted_pilot_count": 0, "human_reviewed_label_count": 0,
            "production_real_id_count": 0,
            "output_hashes": {name: "0" * 64 for name in development_data.PDS01_GROUPS},
        }
        manifest["output_hashes"][group] = hashlib.sha256(_canonical(hashes)).hexdigest()
        manifest_bytes = canonical_bytes(manifest)
        (root / "manifest.json").write_bytes(manifest_bytes)
        return hashlib.sha256(manifest_bytes).hexdigest(), evidence_id

    def test_pinned_private_scope_and_immutable_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin, evidence_id = self._private_fixture(root)
            with patch.object(development_data, "PDS01_MANIFEST_SHA256", pin):
                data = load_private_pds01_group(root, "S07")
            self.assertEqual((data.partition, data.lineage_group, data.tenant_id),
                             ("train_designated_grouped", "PDS01_ALL", "UNKNOWN"))
            event = data.resolve(evidence_id, incident_id=data.incident_id, tenant_id="UNKNOWN")
            self.assertEqual(event["event_data"]["CommandLine"], "[REDACTED]")
            self.assertEqual(event["source_ref"], "SYN-REF-1")
            self.assertEqual(event["timestamp_original"], "2026-01-01T00:00:01Z")
            with self.assertRaises(TypeError):
                event["event_data"]["Image"] = "changed"
            for scope in (("other", "UNKNOWN"), (data.incident_id, "other")):
                with self.assertRaises(PermissionError):
                    data.resolve(evidence_id, incident_id=scope[0], tenant_id=scope[1])

    def test_unverified_manifest_and_output_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin, _ = self._private_fixture(root)
            with self.assertRaisesRegex(ValueError, "unverified_development_manifest"):
                load_private_pds01_group(root, "S07")
            with patch.object(development_data, "PDS01_MANIFEST_SHA256", pin):
                (root / "S07" / "events.jsonl").write_bytes(b"{}\n")
                with self.assertRaisesRegex(ValueError, "unverified_development_output"):
                    load_private_pds01_group(root, "S07")

    def test_missing_identity_foreign_tenant_redaction_and_partition_rejected(self):
        for change, bundle_change, error in (
                ({"source_ref": ""}, None, "cross_incident_or_tenant_event"),
                ({"evidence_id": ""}, None, "evidence_index_mismatch"),
                ({"tenant_id": "OTHER"}, None, "cross_incident_or_tenant"),
                ({"incident_id": "OTHER"}, None, "cross_incident_or_tenant"),
                ({"event_data": {"CommandLine": "secret"}}, None, "s07_redaction_failed"),
                (None, {"partition": "test"}, "invalid_development_scope"),
                (None, {"lineage_group": "OOD"}, "invalid_development_scope")):
            with self.subTest(error=error, change=change, bundle_change=bundle_change):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    pin, _ = self._private_fixture(root, event_change=change,
                                                   bundle_change=bundle_change)
                    with patch.object(development_data, "PDS01_MANIFEST_SHA256", pin):
                        with self.assertRaisesRegex(ValueError, error):
                            load_private_pds01_group(root, "S07")

    def test_gold_and_reviewed_annotations_rejected(self):
        for change in ({"gold_status": "GOLD"},
                       {"annotation_source": "human_reviewed", "human_label": "ACCEPTED"}):
            with self.subTest(change=change):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    pin, _ = self._private_fixture(root, annotation_change=change)
                    with patch.object(development_data, "PDS01_MANIFEST_SHA256", pin):
                        with self.assertRaises(ValueError):
                            load_private_pds01_group(root, "S07")

    def test_synthetic_only_and_scope(self):
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bundle = IncidentBundle(incident_id="SYN-1", tenant_id="TENANT-SYN",
                                environment_id="SYNTHETIC", source_dataset="synthetic",
                                scenario_family="test", alert_ids=(), evidence_ids=("EV-1",))
        event = EvidenceEvent(evidence_id="EV-1", incident_id="SYN-1",
                              tenant_id="TENANT-SYN", normalized_fields={"host": "safe"},
                              provenance=EvidenceProvenance(
                                  source="synthetic:fixture", timestamp_utc=stamp,
                                  raw_message="synthetic event", raw_message_ref="synthetic:1",
                                  sha256="a" * 64, acquisition_method="synthetic"))
        data = from_synthetic_fixture(bundle, [event])
        self.assertEqual(data.resolve("EV-1", incident_id="SYN-1", tenant_id="TENANT-SYN")
                         ["source_ref"], "synthetic:1")
        with self.assertRaises(ValueError):
            from_synthetic_fixture(bundle, [event.model_copy(update={"tenant_id": "OTHER"})])
        with self.assertRaises(ValueError):
            from_synthetic_fixture(bundle.model_copy(update={"environment_id": "OOD"}), [event])


if __name__ == "__main__":
    unittest.main()
