import copy
import hashlib
import unittest

from metaweb_swarm.dedup import identity, merge_submission, normalize_key, resolve
from metaweb_swarm.storage import canonical


def candidate(provider="ORCID", title="Public ORCID recovery pointer", mechanism="Public record links to preserved ZIPs", **changes):
    data = {"provider": provider, "title": title, "mechanism": mechanism,
            "mechanism_kind": "OTHER", "novelty_class": "POTENTIALLY_NEW", "novelty_delta": "",
            "status": "INVESTIGATING", "payment": "FREE", "blocker": "", "rejection_reason": "",
            "evidence": [], "artifact_checks": [], "failure_domains": [], "policy_notes": [],
            "baseline_evidence_ids": [], "id": "IDEA-0001"}
    data.update(changes)
    data["fingerprint"] = hashlib.sha256(canonical([data["mechanism"], data["provider"], data["title"]]).encode()).hexdigest()
    return data


def evidence():
    return [{"url": url, "claim": "Public record supports links", "verified": True,
             "url_observed_in_this_agents_tools": True} for url in ("https://orcid.org/a", "https://info.orcid.org/b")]


class DedupTests(unittest.TestCase):
    def test_real_qr_duplicate_with_same_claim_and_different_agent_key_merges(self):
        a = candidate('QR code + XMP metadata', 'Printed QR card with XMP payload', 'Printed QR recovery pointer', mechanism_key='qr-xmp-recovery-card', mechanism_scope='printable-card')
        b = candidate('QR code + XMP metadata', a['title'], a['mechanism'], mechanism_key='qr-xmp-printable-card', mechanism_scope='printable-card')
        self.assertIs(resolve([a], b), a)
        self.assertIs(resolve([a], b, a['id']), a)
        b['mechanism_scope'] = 'digital-image'
        self.assertIsNone(resolve([a], b))

    def test_real_cc_rel_scope_aliases_merge_without_collapsing_other_features(self):
        a = candidate('Creative Commons / CC REL', 'CC REL-embedded license plaque', 'RDFa recovery pointer in a license plaque', mechanism_key='cc-rel-recovery-pointer', mechanism_scope='license-plaque')
        b = candidate('Creative Commons / CC REL', a['title'], 'CC REL RDFa license plaque carrying the recovery pointer', mechanism_key='cc-rel-license-plaque', mechanism_scope='rdfa-plaque')
        self.assertIs(resolve([a], b), a)
        self.assertIs(resolve([a], b, a['id']), a)
        b['mechanism_scope'] = 'embedded-build-bytes'
        self.assertIsNone(resolve([a], b))

    def test_actual_orcid_mislabeled_kind_and_paraphrase_merge(self):
        a = candidate(mechanism_kind="REGISTRATION", mechanism="ORCID iD record carries recovery pointers and canonical author identity.")
        b = candidate(title="ORCID public record as a reconstructable recovery pointer for personal preservation",
                      mechanism="Public ORCID API record links to preserved artifact packages; follow the pointers.",
                      novelty_class="UNASSESSED", novelty_delta="Use the public record as a reconstruction pointer and identity anchor.")
        self.assertNotEqual(a["fingerprint"], b["fingerprint"])
        self.assertEqual(identity(a), identity(b))
        self.assertIs(resolve([a], b), a)

    def test_actual_s3_titles_and_mechanism_prose_merge(self):
        a = candidate("Amazon S3", "S3 Object Lock + delete-marker replication as a reconstructable tombstoned record layer",
                      "Versioned objects with Object Lock retention/legal hold, replicate delete markers plus retention metadata to a second bucket/region.")
        b = candidate("AWS S3", "Amazon S3 Object Lock + delete-marker replication as a reconstructable tombstoned record layer",
                      "S3 versioning with Object Lock and replication of delete markers plus version metadata into a second bucket.",
                      status="REJECTED", rejection_reason="Unsupported storage payment")
        self.assertEqual(identity(a), identity(b))
        self.assertIs(resolve([a], b), a)

    def test_s3_scope_variants_are_not_collapsed(self):
        a = candidate("Amazon S3", "Object Lock", "Use retained versioned S3 objects with Object Lock compliance mode")
        b = candidate("Amazon S3", "Object Lock", "Use retained versioned S3 objects with Object Lock governance mode")
        c = candidate("Amazon S3", "Object Lock", "Replicate delete markers and Object Lock retained S3 objects")
        self.assertNotEqual(identity(a), identity(b))
        self.assertNotEqual(identity(a), identity(c))
        self.assertIsNone(resolve([a], b))

    def test_s3_compatible_third_party_is_not_amazon(self):
        a = candidate("Backblaze B2", "S3 Object Lock", "Use S3-compatible Object Lock retention")
        self.assertIsNone(identity(a))

    def test_explicit_other_provider_citing_aws_is_never_amazon(self):
        amazon = candidate("Amazon S3", "Object Lock", "Use Amazon S3 Object Lock with delete-marker replication")
        for provider in ("Backblaze B2", "Wasabi", "MinIO", "Other host", "Backblaze B2 / AWS S3 alternative"):
            alternative = candidate(provider, "Object Lock alternative to AWS S3", "Implement Object Lock and delete-marker replication as a free alternative to Amazon S3")
            with self.subTest(provider=provider):
                self.assertIsNone(identity(alternative))
                self.assertIsNone(resolve([amazon], alternative))

    def test_aws_amazon_aliases_and_generic_fallback_are_supported(self):
        expected = identity(candidate("Amazon S3", "Object Lock", "Use Object Lock retained objects"))
        for provider in ("AWS / Amazon S3", "Amazon Web Services (S3)", "AWS S3", "S3", "S3 Object Lock", "S3 / Object-Lock", ""):
            data = candidate(provider, "AWS S3 Object Lock", "Use Object Lock retained objects")
            with self.subTest(provider=provider):
                self.assertEqual(identity(data), expected)

    def test_orcid_embedded_content_is_distinct_from_pointer(self):
        embedded = candidate(mechanism="Embed payload as base64 plus a pointer to the decoder")
        self.assertNotEqual(identity(candidate()), identity(embedded))

    def test_incidental_orcid_reference_does_not_change_other_provider(self):
        a = candidate("Other host", "Archive package", "Deposit content, include an ORCID pointer in attribution")
        self.assertIsNone(identity(a))

    def test_novelty_prose_changes_do_not_split_recognized_mechanism(self):
        a = candidate(novelty_class="IMPROVEMENT", novelty_delta="Archive recovery links survive site failure")
        b = candidate(novelty_class="IMPROVEMENT", novelty_delta="Public record can bootstrap restoration")
        self.assertEqual(identity(a), identity(b))

    def test_unknown_paraphrases_do_not_fuzzy_merge(self):
        a = candidate("Unknown service", "Pointer one", "Upload a package")
        b = candidate("Unknown service", "Pointer two", "Upload the archive package")
        self.assertIsNone(identity(a))
        self.assertIsNone(resolve([a], b))
        self.assertIs(resolve([a], copy.deepcopy(a)), a)

    def test_unknown_explicit_key_and_scope_are_normalized(self):
        a = candidate("Unknown service", mechanism_key="Public_Package Deposit", mechanism_scope="Immutable v1")
        b = candidate("Unknown service", title="Different words", mechanism_key="public-package-deposit", mechanism_scope="immutable_v1")
        self.assertEqual(identity(a), identity(b))
        b["mechanism_scope"] = "mutable"
        self.assertIsNone(resolve([a], b))

    def test_invalid_key_and_scope_are_rejected(self):
        for value in ("https://host", "../escape", "a\\b", "\n", "!@#", 3, "a" * 161):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_key(value)

    def test_generic_carrier_improvement_needs_scope_not_prose_hash(self):
        a = candidate("Zenodo", novelty_class="IMPROVEMENT", novelty_delta="Add an independently decodable index")
        self.assertIsNone(identity(a))
        a["mechanism_scope"] = "independent-reconstruction-index"
        self.assertNotEqual(identity(a), identity(candidate("Zenodo")))

    def test_explicit_id_does_not_repurpose_known_mechanism(self):
        with self.assertRaisesRegex(ValueError, "changes mechanism"):
            resolve([candidate()], candidate("Amazon S3", "Object Lock", "Versioned objects with Object Lock"), "IDEA-0001")
        with self.assertRaisesRegex(ValueError, "Unknown IDEA"):
            resolve([candidate()], candidate(), "IDEA-9999")

    def test_explicit_id_cannot_replace_known_family_with_unknown_mechanism(self):
        old = candidate()
        unrelated = candidate("Different provider", "Upload original builds", "Upload original builds into unrelated storage")
        self.assertIsNone(identity(unrelated))
        with self.assertRaisesRegex(ValueError, "changes mechanism"):
            resolve([old], unrelated, old["id"])

    def test_contributors_and_immutable_claims_survive_review(self):
        a = merge_submission(None, candidate(), "AGENT-002", "2026-10-07T10:00:00Z", claimed={"status": "VERIFIED"})
        before = copy.deepcopy(a)
        b = merge_submission(a, candidate(title="Reworded recovery pointer"), "AGENT-005", "2026-10-07T10:01:00Z")
        self.assertEqual(a, before)
        self.assertEqual(b["id"], a["id"])
        self.assertEqual(b["agent_id"], "AGENT-002")
        self.assertEqual(b["contributors"], ["AGENT-002", "AGENT-005"])
        self.assertEqual(b["submissions"][0], a["submissions"][0])
        self.assertEqual(len(b["submissions"]), 2)
        self.assertEqual(b["submissions"][0]["claimed"], {"status": "VERIFIED"})

    def test_weak_reviewer_cannot_erase_checked_evidence_or_upgrade_itself(self):
        a = merge_submission(None, candidate(status="VERIFIED", evidence=evidence()), "AGENT-002", "t1")
        b = merge_submission(a, candidate(), "AGENT-005", "t2")
        self.assertEqual(b["status"], "VERIFIED")
        self.assertEqual(len(b["evidence"]), 2)
        self.assertEqual(b["evidence"][0]["submitted_by"], "AGENT-002")
        self.assertEqual(b["submissions"][1]["normalized"]["evidence"], [])
        forged = merge_submission(None, candidate(status="VERIFIED", evidence=[{"url": "https://orcid.org/a", "verified": True}, {"url": "https://orcid.org/b", "verified": True}]), "AGENT-008", "t3")
        self.assertEqual(forged["status"], "INVESTIGATING")

    def test_soft_rejection_conflict_requires_review_and_retains_evidence(self):
        a = merge_submission(None, candidate(status="VERIFIED", evidence=evidence()), "AGENT-002", "t1")
        b = merge_submission(a, candidate(status="REJECTED", rejection_reason="Capacity seems too small"), "AGENT-005", "t2")
        self.assertEqual(b["status"], "INVESTIGATING")
        self.assertEqual(b["best_evidenced_status"], "VERIFIED")
        self.assertTrue(b["status_conflicts"])
        self.assertEqual(b["submissions"][1]["normalized"]["rejection_reason"], "Capacity seems too small")
        self.assertEqual(len(b["evidence"]), 2)

    def test_host_policy_rejection_is_sticky(self):
        a = merge_submission(None, candidate(status="REJECTED", payment="RECURRING", requires_ongoing_payments=True, rejection_reason="RECURRING_PAYMENT: storage subscription"), "AGENT-002", "t1")
        b = merge_submission(a, candidate(status="VERIFIED", evidence=evidence()), "AGENT-005", "t2")
        self.assertEqual(b["status"], "REJECTED")
        self.assertEqual(b["payment"], "RECURRING")
        self.assertEqual(b["payment_conflicts"], ["RECURRING", "FREE"])

    def test_conflict_survives_later_weak_review_without_losing_progress(self):
        a = merge_submission(None, candidate(status="VERIFIED", evidence=evidence()), "AGENT-002", "t1")
        b = merge_submission(a, candidate(status="REJECTED", rejection_reason="Capacity too small"), "AGENT-005", "t2")
        c = merge_submission(b, candidate(), "AGENT-006", "t3")
        self.assertEqual(c["status"], "INVESTIGATING")
        self.assertEqual(c["best_evidenced_status"], "VERIFIED")
        self.assertTrue(c["status_conflicts"])

    def test_prototype_requires_artifact_receipt_and_completion_requires_host_receipt(self):
        a = merge_submission(None, candidate(status="PROTOTYPED"), "AGENT-008", "t1")
        self.assertEqual(a["status"], "INVESTIGATING")
        b = merge_submission(a, candidate(status="PROTOTYPED", artifact_checks=[{"path": "agents/AGENT-008/workspace/specimen.json", "sha256": "a" * 64}]), "AGENT-008", "t2")
        self.assertEqual(b["status"], "INVESTIGATING")
        b = merge_submission(b, candidate(status='PROTOTYPED', artifact_checks=b['artifact_checks'], test_receipts=[{'host_execution_verified':True, 'artifacts':[{'path':'specimen.json','sha256':'a'*64}]}]), 'HOST', 't2-test')
        self.assertEqual(b['status'], 'PROTOTYPED')
        c = merge_submission(b, candidate(status="COMPLETED"), "AGENT-008", "t3")
        self.assertEqual(c["status"], "PROTOTYPED")
        d = merge_submission(c, candidate(status="COMPLETED", completion_receipts=[{"host_verified": True, "result_id": "receipt-1"}]), "HOST", "t4")
        self.assertEqual(d["status"], "COMPLETED")

    def test_blocker_preserves_prototype_progress(self):
        a = merge_submission(None, candidate(status="PROTOTYPED", artifact_checks=[{"path": "agents/A/workspace/a.bin", "sha256": "b" * 64}], test_receipts=[{'host_execution_verified':True,'artifacts':[{'path':'a.bin','sha256':'b'*64}]}]), "AGENT-008", "t1")
        b = merge_submission(a, candidate(status="BLOCKED", blocker="HUMAN_APPROVAL_REQUIRED"), "AGENT-009", "t2")
        self.assertEqual(b["status"], "BLOCKED")
        self.assertEqual(b["best_evidenced_status"], "PROTOTYPED")
        self.assertTrue(b["artifact_checks"])

    def test_legacy_snapshot_has_explicit_provenance_limitation(self):
        old = candidate(agent_id="AGENT-002", created_at="t0", updated_at="t1")
        merged = merge_submission(old, candidate(), "AGENT-005", "t2")
        self.assertEqual(merged["submissions"][0]["origin"], "legacy_snapshot")
        self.assertTrue(merged["submissions"][0]["author_of_displayed_claim_unverified"])
        self.assertEqual(merged["contributors"], ["AGENT-002", "AGENT-005"])


if __name__ == "__main__":
    unittest.main()
