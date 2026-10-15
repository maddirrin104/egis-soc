# W1-04 annotation guideline — approved v1.0

**Status:** APPROVED v1.0 on 2026-10-15 by the EGIS-SOC project owner (D-009). P-01 through P-08 below are approved W1-04 operational decisions. This document creates no annotations, frozen labels, evaluation access, or empirical result.

## 1. Purpose, scope, terminology, and authority

This guideline describes human annotation for claim–evidence labels and independent critical facts in already scoped EGIS-SOC incident bundles. It covers the RQ1/RQ3 verifier-pair population and RQ2 output/fact judgments. It does not authorize incident detection, remediation, model tuning, or access to sealed test/OOD labels.

Authority, in descending order for this task: the [approved protocol v0.2](./research-protocol.md), [D-007, D-008, and D-009](./context/DECISION_LOG.md), the [W1-03 schemas](../src/egis_soc/schemas.py), the [project contract](../AGENTS.md), [research guardrails](./context/RESEARCH_GUARDRAILS.md), and the [source plan](./EGIS_SOC_Ke_hoach_8_tuan.md). D-008 controls execution order: W6 prepares/audits Environment B and uses pilot/development data; W7 locks methods, completes calibration and required audits, then conditionally evaluates held-out A/B. The source plan's earlier W6 held-out-evaluation row is not permission to evaluate early.

An **atomic factual claim** is an independently assessable assertion about an event, actor, object, time, behavior, outcome, or impact. A **permitted evidence set** is the fixed, incident- and tenant-scoped snapshot for that claim; a citation is a reference to evidence, not a support verdict. **Gold** means independently human-reviewed evaluation annotation, not a generator output or operational inventory. **S/C/I** denotes the only gold support labels: `supported`, `contradicted`, `insufficient`. **Needs Review** is a prediction-routing flag, never a fourth gold label. **CFR** is Critical Fact Recall; **UCR** is Unsupported Claim Rate; **CSA** is Citation Support Accuracy. Existing metric definitions and denominators remain those of protocol Section 6.

The primary RQ1/RQ3 pairs must come from frozen arm-independent LLM drafts, with annotators blinded to V2/V3 outputs. Source-derived and verifier-blind repair claims are separately labeled diagnostics. Claims created by actual V3-directed S3 repair belong to downstream RQ2 output assessment, not the paired RQ1 population. W1-07 owns lineage isolation, pair manifests and sealed access; W5 owns draft archives; W7 owns final scoring. This guideline cannot substitute for those gates.

## 2. Atomic claim segmentation and evidence review

**APPROVED — W1-04 v1.0 (P-01, segmentation).** Preserve the original sentence and create one unit per independently decidable factual proposition. Split conjunctions when one part could have a different support status, including event versus inferred cause, actor versus outcome, and distinct times or hosts. Keep the minimum actor/action/object/time qualifiers needed to test a proposition; retain negation, modality, source attribution, and uncertainty. Do not split a single event into fragments that cannot be judged alone. Record a stable link from each atom to its source span and the predeclared claim-pair population. Fix segmentation before arm predictions are inspected.

For example, “acct-a logged on to WS01 and was compromised” becomes (1) “acct-a logged on to WS01” and (2) “acct-a was compromised.” A successful logon can support the first without proving the second. The alternative of retaining a compound sentence as one unit can conceal mixed support; splitting every noun phrase would inflate denominators and lose assessable meaning. P-01 affects RQ1/RQ3 pair labels and Macro-F1, and RQ2 factual-claim and UCR counts.

**APPROVED — W1-04 v1.0 (P-01, modality boundary).** A hedge does not automatically remove a sentence from factual-claim evaluation. Ask whether the sentence attributes a concrete incident event, outcome, or likelihood to the world; if so, preserve `may`, `likely`, or `possibly` in the atom and judge that qualified proposition against evidence. An observable assertion can be `supported` when recorded at the stated specificity. A qualified inference needs a documented evidential basis for its **stated** strength; mere logical possibility or an annotator's intuition is not support. An unsupported speculative outcome remains a factual assertion and is `insufficient` absent direct refutation. A truthful statement limited to what the available evidence does or does not establish is an uncertainty/evidence-limit statement rather than an affirmative outcome claim; verify that it accurately describes the fixed evidence and split out any embedded event assertion. Do not convert a hedged claim into an unhedged claim during segmentation or grant `supported` merely because “may” makes it difficult to disprove.

| Fully synthetic wording | Approved treatment |
| --- | --- |
| “Security record 101 shows a successful logon for acct-a on WS01.” | Observable factual assertion; evaluate its record, entity, and time. |
| “acct-a may have retried successfully after record 102.” | Qualified factual inference; the later retry needs evidence. A separate earlier 4624 does not support this sequence. |
| “acct-a likely stole credentials after the logon.” | Factual likelihood/outcome assertion; auth and process-start records alone do not establish the likelihood, so `insufficient` on this evidence. No numerical likelihood threshold is invented here. |
| “acct-a possibly started PowerShell on WS01.” | Factual, despite `possibly`; a matching Sysmon process-creation record can support this weaker qualified wording, without proving malicious intent. |
| “These records do not establish exfiltration.” | Truthful evidence-limit statement if accurate for the fixed evidence; it does not assert that exfiltration occurred or did not occur. An added “but exfiltration likely occurred” becomes a separate factual atom. |

Annotators should record the original phrase, segmented atom, modality, and reason for treating an uncertainty sentence as non-factual in the separate audit trail; W1-03 has no dedicated modality field. The alternative of excluding every hedge would shrink RQ2's UCR denominator and alter RQ1/RQ3 claim eligibility after seeing output style. This approved P-01 boundary must be included in the annotation-version lock before those populations are frozen.

Review the fixed permitted evidence, including needed combinations of events, original timestamps/time zones, entities, and provenance. Resolve every cited ID against the same incident and tenant; inspect content and temporal/entity relationships. Do not infer an event from a log's mere absence, assume a source is complete without an approved completeness record, or treat raw log/CTI text as operational instructions. Note relevant evidence IDs and any unresolved provenance or scope problem in the annotation audit trail. Original events and provenance remain immutable. A digest verifies snapshot bytes when W2 implements the raw-store check; it does not prove that the source event is true.

## 3. Three-class S/C/I rubric

| Gold label | Required finding for an atomic claim | What does not suffice |
| --- | --- | --- |
| `supported` | The permitted in-scope evidence, alone or as an allowed combination, supports every factual part at the asserted specificity, including entity, time, event type, negation, and qualification. | An existing citation ID, a merely related event, or a plausible inference. |
| `contradicted` | Permitted evidence directly refutes the asserted proposition at the relevant specificity, with no unresolved part preventing an unambiguous verdict. | Missing telemetry, absence of a confirming event, or a competing hypothesis without direct refutation. |
| `insufficient` | Full support and unambiguous direct refutation are both unavailable, including missing, incomplete, ambiguous, or conflicting evidence. | A presumption that missing evidence means the opposite event happened. |

These three meanings are fixed by [protocol Section 3](./research-protocol.md). For summary UCR, both `contradicted` and `insufficient` count as unsupported factual assertions; a truthful uncertainty statement is handled by the locked claim-type rubric rather than being called an unsupported assertion merely because the underlying event is unknown. A direct contradiction can be supported by an explicit mutually exclusive outcome for the **same identified record or attempt**. A failed login at merely the same time, or at a different time, does not refute a separate successful login.

## 4. Decision procedure, precedence, ambiguity, and edge cases

**APPROVED — W1-04 v1.0 (P-02, operational precedence).** Apply this order to a candidate unit:

1. Verify that the candidate is a factual assertion, retain its qualifiers, and segment it under P-01. Route purely truthful evidence-limit statements to the documented non-factual/uncertainty category; do not drop embedded factual assertions.
2. Confirm the fixed permitted evidence snapshot and incident/tenant scope. Record emitted citation resolution separately from support. Missing or out-of-scope references cannot expand the permitted set or themselves establish `supported` or `contradicted`.
3. If all relevant permitted evidence fully supports the atom at its asserted specificity and no material source conflict remains unresolved, assign `supported`.
4. Otherwise, if it directly refutes the atom without unresolved qualifying facts or material source conflict, assign `contradicted`.
5. Otherwise assign `insufficient`. Flag material ambiguity for human adjudication before a gold record is finalized. Preserve the initial judgments and resolution reason.

Atomization comes before label precedence. If a compound claim remains inseparable and mixes support with refutation or uncertainty, do not force `contradicted`: adjudicate the boundary and label only after the unit is made assessable. If two in-scope records conflict and source priority or timing cannot resolve them under a predeclared rule, use `insufficient` pending adjudication. The alternative “any refuted subpart makes the whole sentence Contradicted” would differ from the approved protocol's unresolved-atom condition. P-02 affects RQ1/RQ3 class prevalence, false-support analysis, and RQ2 unsupported counts.

**APPROVED — W1-04 v1.0 (P-02, evidence-versus-citation application).** In E1/RQ1/RQ3, `EvaluationClaimEvidencePair.evidence_ids` is the fixed permitted **pair evidence set**: adjudicate the atom using that set and its permitted combination, not another event in the broader bundle and not a verifier's emitted citations. A same-incident record omitted from the pair cannot rescue its label. An irrelevant extra record **inside** the fixed pair set does not by itself negate otherwise complete semantic support from a relevant record. In E2/RQ2, adjudicate each emitted factual summary claim for UCR against the fixed permitted **incident evidence**, cited or uncited. Separately, check each emitted citation for in-scope validity and relevance; CSA requires the cited combination to support the claim and rejects invalid, out-of-scope, or irrelevant extras. Thus a valid but irrelevant extra citation can leave E1 S/C/I and E2 UCR support unchanged while preventing that cited claim from entering CSA's numerator. A missing or cross-incident citation is invalid and cannot enlarge either evidence set. The approved CV, CSA, and UCR formulas and denominators are unchanged; P-04 still defines relevance.

Reject cross-incident or cross-tenant evidence references through scope validation before using them in an evaluation pair. If a scope violation is discovered after the test manifest is frozen, record the protocol deviation and apply the prespecified failure/exclusion policy under W1-07/W7. Do not silently remove pairs, alter denominators, or revise the test population after inspecting predictions. Foreign evidence remains outside the permitted set and does not create a new S/C/I label.

| Fully synthetic case | E1 pair label if this is its fixed pair set | E2 summary assessment using the same incident snapshot |
| --- | --- | --- |
| Claim “record 101 shows success”; pair has only relevant `E-SYN-001` (4624). | `supported`. | UCR claim is supported. A sole citation to `E-SYN-001` can satisfy CSA if relevant. |
| Same claim; pair has `E-SYN-001` plus unrelated same-incident `E-SYN-002` (4625 record 102). | Still `supported`: extra permitted context does not refute record 101. | If both IDs are *emitted citations*, the extra is valid but irrelevant: UCR support remains, CSA numerator fails under the approved rule. |
| Same claim; pair has only `E-SYN-002`. | `insufficient`: record 101 is outside this pair, even though it exists in the bundle. | UCR can still be supported by permitted incident record 101; a sole citation to record 102 fails CSA support. |
| Claim “Security record 102 reports success”; pair has `E-SYN-002`, whose 4625 outcome is failure. | `contradicted` for the same record identity. | UCR counts the assertion unsupported; a citation to the failed record cannot make CSA correct. |
| A summary cites `E-SYN-OTHER`, belonging to another incident, alongside valid `E-SYN-001`. | A pair attempting to include `E-SYN-OTHER` fails scope validation; do not label it as a valid pair. | Foreign citation is invalid and CSA numerator fails; record 101 may still support UCR's factual claim within the permitted incident evidence. |

| Synthetic edge case | Approved treatment and reason |
| --- | --- |
| Record 101 shows a successful login at 10:00; claim says “Security record 102 reports success”; record 102 explicitly reports failure. | `contradicted` for that same record's stated outcome; do not use the separate record 101 to support it. |
| A DNS query exists; claim says “data was exfiltrated.” | `insufficient`: DNS alone does not establish transfer or outcome. |
| The only expected telemetry is absent. | `insufficient`, unless a separately approved, complete source record directly refutes the claim. |
| Two records disagree about the event and neither has established priority. | `insufficient` with adjudication; do not select whichever favors a model. |
| “The available evidence does not establish exfiltration.” | A truthful uncertainty statement, not an affirmative exfiltration assertion. Any separate factual assertion in the sentence is still segmented. |

`Needs Review` may be emitted by the verifier with a three-class prediction, but it is not placed in `EvaluationClaimEvidencePair.label`. The protocol's review mapping for low confidence, missing evidence, or unresolved rule/NLI disagreement is predicted `insufficient` plus `review_required=true`; a high-confidence direct contradiction may retain predicted `contradicted` while flagged. Exact routing triggers and thresholds require validation-data selection and owner approval before test. All routed and failed pairs remain in the fixed scoring denominator under the protocol's missing-output policy.

## 5. Independent gold critical-fact construction

Human annotators build evaluation facts from the incident timeline and permitted source evidence **before seeing generated drafts, model predictions, arm identities, or S3's operational fact inventory**. A candidate fact states an independently testable incident detail, with its supporting evidence IDs and source-event provenance. The source plan's initial trigger, affected entities, timeline, observed behavior, confirmed outcome, impact, uncertainty, and limitations are prompts for coverage, not extra W1-03 schema fields or a requirement to invent unobserved facts.

The evaluation inventory is held separately as `EvaluationGoldRecord`, matched to the same incident, tenant, and evidence snapshot. The inference-facing `IncidentBundle` must never contain evaluation facts. An operational inventory for S3 may use only the evidence/metadata allowed to both arms, and must not receive evaluation fact IDs, labels, or adjudications. Separate storage and an access audit are required before scoring; the accepted schema alone does not enforce access control. Evaluation output annotators may inspect reports to judge coverage/support, but must be blinded to S2/S3 arm identity and predictions. Document and resolve any blinding breach.

Do not derive gold facts solely from generated summaries or treat model predictions as truth. A candidate fact that is disputed, unobservable, or not fully supported stays visible in the audit with an explicit adjudication outcome; it is not silently treated as false or inserted into CFR's eligible denominator. No real gold fact is created by this guideline.

## 6. Criticality, observability, support, and CFR eligibility

The approved [protocol Section 6.2](./research-protocol.md) includes only independently annotated facts that are critical, `supported`, and observable from the permitted evidence in CFR; low-criticality facts are not mandatory. The schema permits `criticality` values `low`, `medium`, `high`, a three-class `support_status`, and a nonblank free-text `observability`. It does not encode the W1-04 approved eligibility threshold or an observability enum.

**APPROVED — W1-04 v1.0 (P-03, fact eligibility).** Mark `high` when omission would materially distort the incident's trigger, actor/entity, key timeline step, confirmed outcome, or analyst interpretation; mark `medium` when omission would remove a meaningful but nonessential supported step; mark `low` for incidental detail. Treat `high` and `medium` as critical for CFR only if `support_status="supported"` and the whole fact is observable in the fixed permitted evidence. Use documented observability wording such as `observable`, `partially observable`, or `not observable` in the existing free-text field; this is approved annotation vocabulary, not a schema enum. Split a partly observable candidate into independently assessable facts before deciding eligibility. A fact remains in the audit when excluded, with its reason and adjudication outcome.

For example, an observed successful logon that anchors the incident timeline can be `high` and eligible; an observed auxiliary process ID may be `low` and ineligible. “The attacker stole credentials” is not eligible merely because a login occurred. An alternative high-only CFR threshold would reduce the denominator and change measured coverage; treating partly observed inferred outcomes as eligible would overstate omissions and reward unsupported report text. P-03 directly affects RQ2 CFR and omission counts, and can indirectly alter S3 repair evaluation; it does not change the approved CFR formula. Report eligible and excluded counts by incident after adjudication, without using S2/S3 output quality to set eligibility.

**APPROVED — W1-04 v1.0 (P-03, operational anchors).** Judge criticality from the independent source timeline before inspecting either report. `high` means removing the fact changes a reader's answer to what happened, which entity was affected, or the decisive order/outcome; `medium` means it preserves a meaningful distinct step but the core incident interpretation survives its omission; `low` means incidental detail or redundant specificity. A Sysmon process-creation event may be `high` if it is the only supported execution step that defines the incident, or `medium` if several other events already establish that step; the event type alone does not set criticality. A successful 4624 logon on the affected host may be `high` when it is the initial confirmed access event relevant to the triaged incident, or `medium` when it is one of several equivalent logons and adds only timeline detail. These borderline cases require the annotator to cite the incident role and the adjudicator to compare that rationale against the fixed evidence, without consulting S2/S3 outputs.

| Fully synthetic candidate fact | Approved status and CFR eligibility |
| --- | --- |
| “Record 101 confirms a successful acct-a logon on affected WS01”; decisive initial event, supported by `E-SYN-001`, fully observable. | `high`, `supported`, `observable`: eligible. |
| “A PowerShell process for acct-a was created on WS01 at 10:03”; meaningful subsequent step supported by `E-SYN-003`, fully observable. | `medium`, `supported`, `observable`: eligible under the approved high-or-medium rule, subject to incident-role adjudication. |
| “Security record 102 has an incidental record number”; supported but not needed for the incident account. | `low`, `supported`, `observable`: excluded from CFR. |
| “The PowerShell process stole credentials”; only process creation is observed. | Split the observed creation from the inferred theft. The theft candidate is `insufficient`/not fully observable and excluded; the creation may be eligible on its own. |
| “The attacker completed exfiltration”; no permitted transfer/outcome evidence. | `insufficient`, `not observable`: excluded, even if omission would otherwise seem important. |

Adjudicate in this order: atomize partial facts; confirm support against permitted evidence; decide whether the entire atom is observable; then assign criticality from its incident role. If annotators disagree on high versus medium, record the competing incident-role rationales even though both are provisionally eligible under P-03; if they disagree on medium versus low, support, or observability, resolve before fixing the eligible set because the CFR denominator can change. Keep `partially observable` as an explicit audit outcome until the candidate is split or excluded; do not count it as fully eligible. This approval does not add a `GoldFact` enum or change the protocol's CFR formula or denominator policy.

## 7. Citation validity, relevance, and semantic support

Assess three questions separately. **Validity:** does each cited ID resolve to an evidence record in the permitted incident and tenant? **Relevance:** does that record bear on the specific atom or a necessary bridge in its proof? **Support:** does the permitted combination of cited content fully justify the atom? A valid reference can be irrelevant; relevant evidence can still be insufficient. All factual claims, including uncited claims, remain subject to S/C/I support review and UCR. CSA's approved numerator requires fully supported cited claims and rejects invalid, out-of-scope, or irrelevant extra citations.

**APPROVED — W1-04 v1.0 (P-04, extra-citation relevance).** An extra citation is relevant if it directly supports an atom, corroborates a disputed attribute, or supplies a necessary temporal/entity bridge for the stated inference. Mere co-occurrence in the same incident, matching a keyword, or appearing near the cited event is not enough. Assess every emitted citation occurrence; one irrelevant or invalid extra reference prevents that cited factual claim from entering CSA's fully supported numerator, even if another citation proves the claim. Do not change the claim's S/C/I label merely because a superfluous citation was emitted: assess factual support against the permitted evidence under the applicable pair/summary policy, and report the citation defect separately.

For example, a successful-login event supports “acct-a logged on to WS01”; an unrelated firewall event from the same incident does not become relevant when added as a second citation. The alternative of ignoring surplus citations would inflate CSA and weaken the protocol's explicit extra-citation rule. P-04 affects RQ2 CSA and RQ1 citation diagnostics, but not the approved citation-validity denominator or S/C/I definitions. A citation to another tenant or incident is invalid regardless of apparent semantic relevance.

## 8. Semantic coverage and introduced S2/S3 claims

**APPROVED — W1-04 v1.0 (P-05, fact coverage).** Count an eligible gold fact as covered only when the report conveys the same event/relationship at compatible entity, time, outcome, negation, and confidence, without adding an unsupported stronger assertion. Exact wording or citation formatting is unnecessary; a correctly qualified paraphrase may cover the fact. A bare keyword, a generic “suspicious activity” label, or a stronger unsupported outcome does not. Ambiguous matches receive human adjudication before scoring and retain the original judgments. For example, “a successful logon for acct-a on WS01 was recorded at 10:00 UTC” covers an equivalent gold fact; “acct-a was compromised” does not establish or faithfully cover that observed logon. The alternative of loose keyword matching would inflate RQ2 CFR. P-05 affects RQ2 CFR/omission decisions, not gold-fact construction.

**APPROVED — W1-04 v1.0 (P-05, coverage procedure).** Before viewing S2/S3 outputs, identify for each eligible gold fact the attributes required to preserve its meaning: event identity/type, actor or affected entity, observed outcome, necessary temporal order or precision, negation, and qualification. Mark incidental details that can be omitted or generalized without changing the proposition, such as a record number when the event is otherwise uniquely identified. Then compare each report mention with that fixed attribute set. Event and actor must refer to the same incident occurrence; an identical event type on another host or account is not a match. A later event cannot cover an earlier one. A successful outcome cannot be covered by “an attempt occurred”; a failed outcome cannot be covered by success. Negation must retain its scope. “May have occurred” does not fully cover an independently confirmed event if it weakens the reported outcome; an unqualified outcome cannot cover a gold fact whose uncertainty is essential. Exact clock time is required only when fixed as meaning-bearing; otherwise a compatible time interval or order may suffice. Citation correctness is assessed separately, but an unsupported mention cannot earn coverage.

| Audit judgment, not a W1-03 gold label | Decision rule | Synthetic example against gold “a successful logon for acct-a on WS01 was recorded at 10:00 UTC” |
| --- | --- | --- |
| Fully and faithfully covered | All required attributes and qualifications are present or semantically equivalent; no stronger unsupported assertion is used as the match. | “Windows Security record 101 reports a successful logon for acct-a on WS01 at 10:00 UTC.” |
| Partially covered | A relevant mention exists, but a required actor, outcome, temporal distinction, or qualification is missing or weakened. | “A logon attempt occurred on WS01”; success and actor are missing. |
| Ambiguous | Two plausible event referents or interpretations remain after fixed-evidence review. Escalate to blinded adjudication and retain the disagreement. | “The later logon succeeded” when several later logons exist. |
| Not covered | No matching mention, an incompatible event/entity/negation, or only an unsupported stronger outcome appears. | “acct-a was compromised” with no faithful mention of the successful logon. |

Only **fully and faithfully covered** eligible facts enter CFR's existing numerator. Partial and not-covered facts do not; unresolved ambiguous judgments cannot be silently credited and must be disclosed/adjudicated before scoring. These audit categories do not add S/C/I labels or alter `GoldFact.support_status`. A stricter exact-string/time rule would undercount faithful paraphrases; a looser keyword rule would inflate RQ2 CFR. The required/incidental attribute decision and its version must be locked before reports are compared.

In the synthetic 4624 example, “successful logon” describes only the recorded event and its account, host, and time. The evidence does not specify LogonType, an interactive human sign-in, or compromise; none may be inferred for coverage credit.

**APPROVED — W1-04 v1.0 (P-06, introduced unsupported claims).** First atomize and adjudicate every S2 and S3 factual assertion against the same permitted evidence. For each S3 `contradicted` or `insufficient` atom, look for an S2 `contradicted` or `insufficient` predecessor that asserts the same proposition at compatible entity, event, time, outcome, negation, and qualification. A paraphrase can match; a materially stronger, broader, shifted, or newly causal assertion cannot. Compare to the archived common S2 fork; an S2 `supported` atom is not an unsupported predecessor. For example, S2 “a login occurred” and S3 “the account was compromised” are not equivalent. The alternative of matching on shared entities or keywords would hide repair-induced errors. P-06 affects mandatory RQ2 introduced-claim and dilution diagnostics, not the approved pooled-UCR margin or formula.

**APPROVED — W1-04 v1.0 (P-06, predecessor cardinality).** Use **predecessor existence**, not one-to-one consumption: classify each S3 C/I atom independently. If any semantically equivalent S2 C/I predecessor exists, that S3 atom is not introduced, even when several S3 paraphrases or duplicates point to the same S2 atom. If no predecessor exists, each unsupported S3 occurrence is introduced, including repeated new assertions. A stronger or newly causal S3 atom lacks an equivalent predecessor even if it shares actors or keywords. Under this approved occurrence rule, each repeated emitted atomic factual assertion counts separately in UCR's factual and unsupported counts; semantic predecessor matching does not deduplicate output claims. Retain duplicate unsupported occurrences in per-incident and aggregate absolute-count and length diagnostics. Lock segmentation, occurrence counting, and predecessor matching before final evaluation, without changing the approved pooled UCR formula, margin, or denominators. One-to-one matching would classify a duplicate S3 assertion as introduced after the first match consumes its S2 predecessor, changing the introduced-claim diagnostic. These cardinality and repeated-occurrence choices are approved for W1-04; scoring implementation and pre-test locks remain downstream gates.

| Fully synthetic S2/S3 C/I pattern | Approved predecessor-existence result |
| --- | --- |
| S2: “acct-a was compromised.” S3 repeats that assertion twice, once as a paraphrase. | Both S3 occurrences have an equivalent S2 C/I predecessor; zero are introduced, but both count as unsupported S3 assertions. Under one-to-one matching, one duplicate could be classified introduced. |
| S2 has no exfiltration claim. S3 says twice “acct-a exfiltrated data.” | Both S3 occurrences are introduced and remain in unsupported and length counts. |
| S2: “acct-a was compromised.” S3: “the compromise caused exfiltration.” | New causal/outcome proposition; introduced unless another equivalent S2 C/I atom exists. |
| Two S2 claims could plausibly be predecessors but time/entity details are unclear. | Record the relationship as ambiguous and adjudicate blinded to arm outcomes; report unresolved ambiguity separately, not as an automatic match or definite introduction. |

For equivalence adjudication, show masked claim text and permitted evidence without model scores or arm labels; a custodian applies the archived S2/S3 direction after semantic judgments. For each incident, report definite introduced C/I occurrences, ambiguous predecessor relationships, total unsupported and factual claims, uncited claims, claim/token lengths, and incidents with an increase, as required by the protocol. Resolve ambiguous matches before a final introduced count where possible; if not, disclose the unresolved count and the resulting diagnostic uncertainty without changing UCR, CFR, or the fixed incident set. The one-to-one alternative and its effect on duplicate classification remain documented as rationale; predecessor existence is the approved W1-04 rule.

## 9. Independent annotation, blinding, disagreements, and adjudication

**APPROVED — W1-04 v1.0 (P-07, workflow).** Before inspecting outcomes, predeclare and document a test/OOD subset for independent double annotation, including how incidents/pairs/facts are sampled and how A/B and source families are represented. The approved protocol requires at least a documented subset; it approves **no percentage**. Two annotators independently receive the same fixed permitted evidence and this rubric. For primary RQ1/RQ3 pairs, both are blind to V2/V3 outputs and to each other's judgments. For RQ2 evaluation facts, they are also blind to drafts, arm identities, predictions, and the operational inventory. For output-claim support and coverage, reports are necessarily visible but arm identity and predictions remain masked.

Retain each initial label or fact proposal, supporting/refuting evidence IDs, rationale and reason code, the disagreement category, any blinding incident, adjudicator and resolution. Approved reason-code categories are atom boundary, evidence scope/provenance, entity/time mismatch, support versus inference, direct refutation, criticality/observability, semantic match, citation relevance, and other with explanation; these are approved audit vocabulary, not W1-03 enum values. Have a designated adjudicator review disagreements against the fixed snapshot and the approved rubric. Do not erase initial records. If unresolved, retain an explicit unresolved state in the audit and withhold that judgment from a frozen gold record until resolved under the prespecified eligibility policy; disclose counts and reasons, and never change an evaluation denominator after viewing scores. The alternative of consensus discussion before independent records would make agreement unmeasurable. P-07 affects gold reliability for all three RQs.

The current `EvaluationClaimEvidencePair` carries `annotation_record_id` and `annotation_source="human_reviewed"`; `GoldFact` carries only `annotation_source="human_reviewed"`. W1-03 does **not** provide fields for annotator/adjudicator IDs, independent initial judgments, annotation time, reason codes, disagreement history, blinding/access audit, source-event links beyond evidence IDs, or a per-fact annotation-record reference. Retain this required metadata in a separate controlled annotation audit record linked by existing incident/pair/fact identifiers, pending a separately reviewed storage/schema design. This document neither defines new W1-03 fields nor asserts that the audit store exists. A literal `human_reviewed` value is a contract marker, not proof that independent review occurred.

## 10. Annotation agreement methodology

**APPROVED — W1-04 v1.0 (P-08, agreement).** For two independent annotators judging the **same fixed atomic claim–evidence units**, use unweighted Cohen's kappa as the primary chance-corrected S/C/I agreement statistic, accompanied by raw percent agreement, a 3×3 rater cross-tabulation, class prevalence, counts of incidents/pairs per environment, and the number of unresolved cases. This is appropriate for two raters and nominal, mutually exclusive labels; do not calculate it on adjudicated labels or silently discard initial disagreements. Prespecify unit alignment and the double-annotation sample before viewing agreement or model results. If a class is absent or prevalence is highly skewed, report kappa's limitation and a prespecified Gwet's AC1 sensitivity result; neither replaces the raw cross-tabulation. Report `NA` with the reason if a statistic is undefined. Do not imply a measured value exists now.

Fact discovery and atom segmentation may produce different units for different annotators; a kappa over unmatched units would be misleading. Record unit-boundary and fact-candidate disagreements separately, reconcile the candidate set under P-07, and then report agreement on common fixed fact-eligibility judgments if that exercise was independently double coded. The alternative of reporting only post-adjudication consensus would conceal initial variability. P-08 affects the credibility and interpretation of gold used by RQ1/RQ2/RQ3, not the approved primary metrics. The source plan permits kappa or AC1 as examples; W1-04 approves kappa as primary with AC1 sensitivity, without setting a sample fraction.

## 11. Synthetic worked examples using W1-03 contracts

All identifiers, account/host names, record numbers, correlations, and messages below are **synthetic**. The event-type meanings follow Microsoft's descriptions of [Windows Security 4624](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-4624), [Windows Security 4625](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-4625), and [Sysmon Event ID 1](https://learn.microsoft.com/sysinternals/downloads/sysmon); the shown lines are invented simplified messages, not authentic Windows event serialization. The `human_reviewed` literals illustrate the approved **shape** only; they do not claim a person annotated these invented examples. The evaluation record is separate from the inference bundle. The synthetic event hashes are SHA-256 over the exact UTF-8 `raw_message` strings shown; no raw-store ingestion or digest verification is claimed.

### 11.1 Inference-facing incident bundle

```json
{
  "incident_id": "INC-SYN-001",
  "tenant_id": "TENANT-SYN",
  "environment_id": "ENV-A-PILOT",
  "source_dataset": "synthetic",
  "scenario_family": "authentication",
  "alert_ids": ["ALT-SYN-001"],
  "evidence_ids": ["E-SYN-001", "E-SYN-002", "E-SYN-003"]
}
```

### 11.2 Evidence events and provenance

```json
[
  {
    "evidence_id": "E-SYN-001",
    "incident_id": "INC-SYN-001",
    "tenant_id": "TENANT-SYN",
    "normalized_fields": {"event_id": 4624, "record_id": 101, "outcome": "success", "account": "acct-a", "host": "WS01"},
    "provenance": {
      "source": "synthetic-auth-log",
      "timestamp_utc": "2026-10-12T10:00:00Z",
      "raw_message": "2026-10-12T10:00:00Z Security EventID=4624 RecordID=101 Host=WS01 Account=acct-a Outcome=Success",
      "raw_message_ref": "snapshot:synthetic/E-SYN-001",
      "sha256": "11e08099f359ff0bf9902ca5b791e7288b3418df8d7982ebf098b2b344bf94d8",
      "acquisition_method": "synthetic-fixture"
    }
  },
  {
    "evidence_id": "E-SYN-002",
    "incident_id": "INC-SYN-001",
    "tenant_id": "TENANT-SYN",
    "normalized_fields": {"event_id": 4625, "record_id": 102, "outcome": "failure", "account": "acct-a", "host": "WS01"},
    "provenance": {
      "source": "synthetic-auth-log",
      "timestamp_utc": "2026-10-12T10:05:00Z",
      "raw_message": "2026-10-12T10:05:00Z Security EventID=4625 RecordID=102 Host=WS01 Account=acct-a Outcome=Failure",
      "raw_message_ref": "snapshot:synthetic/E-SYN-002",
      "sha256": "e476d018a3a2d195ed7f8aebf9834a8c9158737dbc460d5be66bc823a0d371aa",
      "acquisition_method": "synthetic-fixture"
    }
  },
  {
    "evidence_id": "E-SYN-003",
    "incident_id": "INC-SYN-001",
    "tenant_id": "TENANT-SYN",
    "normalized_fields": {"event_id": 1, "record_id": 201, "user": "acct-a", "host": "WS01", "image": "powershell.exe", "process_guid": "SYN-GUID-201"},
    "provenance": {
      "source": "synthetic-sysmon",
      "timestamp_utc": "2026-10-12T10:03:00Z",
      "raw_message": "2026-10-12T10:03:00Z Sysmon EventID=1 RecordID=201 Host=WS01 User=acct-a Image=powershell.exe ProcessGuid=SYN-GUID-201",
      "raw_message_ref": "snapshot:synthetic/E-SYN-003",
      "sha256": "6fdb3820d6a34bec0af7281587560feb4d908bd4ddfbfeefa292c23af7fba1b3",
      "acquisition_method": "synthetic-fixture"
    }
  }
]
```

### 11.3 Separate evaluation gold record

```json
{
  "incident_id": "INC-SYN-001",
  "tenant_id": "TENANT-SYN",
  "evidence_ids": ["E-SYN-001", "E-SYN-002", "E-SYN-003"],
  "gold_facts": [
    {
      "fact_id": "F-SYN-001",
      "statement": "A successful logon for acct-a on WS01 was recorded at 10:00 UTC",
      "criticality": "high",
      "support_status": "supported",
      "evidence_ids": ["E-SYN-001"],
      "observability": "observable",
      "annotation_source": "human_reviewed"
    },
    {
      "fact_id": "F-SYN-002",
      "statement": "A PowerShell process for acct-a was created on WS01 at 10:03 UTC",
      "criticality": "medium",
      "support_status": "supported",
      "evidence_ids": ["E-SYN-003"],
      "observability": "observable",
      "annotation_source": "human_reviewed"
    }
  ]
}
```

### 11.4 Evaluation claim–evidence pairs

```json
[
  {
    "pair_id": "P-SYN-001",
    "incident_id": "INC-SYN-001",
    "tenant_id": "TENANT-SYN",
    "claim": "A successful logon for acct-a on WS01 occurred at 10:00 UTC",
    "evidence_ids": ["E-SYN-001"],
    "claim_type": "observed_event",
    "label": "supported",
    "annotation_source": "human_reviewed",
    "claim_source": "generated_draft",
    "annotation_record_id": "REVIEW-SYN-001"
  },
  {
    "pair_id": "P-SYN-002",
    "incident_id": "INC-SYN-001",
    "tenant_id": "TENANT-SYN",
    "claim": "Windows Security record 102 on WS01 reports a successful logon for acct-a",
    "evidence_ids": ["E-SYN-002"],
    "claim_type": "observed_event",
    "label": "contradicted",
    "annotation_source": "human_reviewed",
    "claim_source": "generated_draft",
    "annotation_record_id": "REVIEW-SYN-002"
  },
  {
    "pair_id": "P-SYN-003",
    "incident_id": "INC-SYN-001",
    "tenant_id": "TENANT-SYN",
    "claim": "The account was compromised",
    "evidence_ids": ["E-SYN-001", "E-SYN-003"],
    "claim_type": "inferred_outcome",
    "label": "insufficient",
    "annotation_source": "human_reviewed",
    "claim_source": "generated_draft",
    "annotation_record_id": "REVIEW-SYN-003"
  },
  {
    "pair_id": "P-SYN-004",
    "incident_id": "INC-SYN-001",
    "tenant_id": "TENANT-SYN",
    "claim": "Sysmon process-creation record 201 for acct-a on WS01 occurred after successful-logon record 101 for acct-a on WS01",
    "evidence_ids": ["E-SYN-001", "E-SYN-003"],
    "claim_type": "temporal_relation",
    "label": "supported",
    "annotation_source": "human_reviewed",
    "claim_source": "generated_draft",
    "annotation_record_id": "REVIEW-SYN-004"
  },
  {
    "pair_id": "P-SYN-005",
    "incident_id": "INC-SYN-001",
    "tenant_id": "TENANT-SYN",
    "claim": "The PowerShell process downloaded a file",
    "evidence_ids": ["E-SYN-003"],
    "claim_type": "inferred_outcome",
    "label": "insufficient",
    "annotation_source": "human_reviewed",
    "claim_source": "generated_draft",
    "annotation_record_id": "REVIEW-SYN-005"
  }
]
```

These five pairs illustrate the three labels, not sampled class balance or an actual frozen RQ1/RQ3 manifest. The 4625 failure in **record 102** directly refutes P-SYN-002's assertion about that same record; it does not refute the separate 4624 success in record 101. P-SYN-004 uses the 4624 and Sysmon Event ID 1 records together to establish temporal order and shared account/host, **not** causation or a shared logon session. P-SYN-005 has partial evidence of process creation but none for a download, so the outcome remains `insufficient`. The two synthetic gold facts are eligible for CFR only under approved P-03 and when real independent review establishes criticality, support, and observability.

### 11.5 Cross-incident reference: expected scope rejection

This invented event belongs to another incident, even though it has the same synthetic tenant. Its source record and hash are illustrative only.

```json
{
  "evidence_id": "E-SYN-OTHER",
  "incident_id": "INC-SYN-OTHER",
  "tenant_id": "TENANT-SYN",
  "normalized_fields": {"event_id": 4624, "record_id": 900, "outcome": "success", "account": "acct-z", "host": "OTHER"},
  "provenance": {
    "source": "synthetic-auth-log",
    "timestamp_utc": "2026-10-12T10:04:00Z",
    "raw_message": "2026-10-12T10:04:00Z Security EventID=4624 RecordID=900 Host=OTHER Account=acct-z Outcome=Success",
    "raw_message_ref": "snapshot:synthetic/E-SYN-OTHER",
    "sha256": "3b1014ba0a88f0cb3546e1c799661f57d6158c0673fd199f9e0107dacd2c27c0",
    "acquisition_method": "synthetic-fixture"
  }
}
```

The following uses only `ClaimEvidencePair` fields but is an **intentionally invalid scoped candidate**, not evaluation gold. W1-03 model construction accepts its field shapes; `IncidentBundle.check_scope` must reject its `E-SYN-OTHER` reference for `INC-SYN-001`. It must not be scored or silently relabeled using foreign evidence.

```json
{
  "pair_id": "P-SYN-FOREIGN",
  "incident_id": "INC-SYN-001",
  "tenant_id": "TENANT-SYN",
  "claim": "A successful logon for acct-z was recorded on OTHER",
  "evidence_ids": ["E-SYN-OTHER"],
  "claim_type": "observed_event",
  "label": "supported",
  "annotation_source": "synthetic_candidate",
  "claim_source": "synthetic_example"
}
```

### 11.6 Synthetic citation, omission, and repair judgments

W1-03 has no summary-output or emitted-citation-list model. The following strings are **synthetic audit examples**, not extra fields in the JSON contracts or measured results.

| Synthetic situation | Approved annotation consequence |
| --- | --- |
| Summary claim “record 101 reports a successful acct-a logon” emits citations `E-SYN-001` and `E-SYN-002`. | Record 101 supports the factual assertion for UCR. Both IDs resolve in scope, but 4625 record 102 is an irrelevant extra for record 101: the claim cannot enter CSA's supported numerator. Its S/C/I support is unchanged solely by the extra citation. |
| The same claim emits `E-SYN-001` and `E-SYN-OTHER`. | The foreign citation is invalid, cannot be used as evidence, and prevents CSA numerator credit. The in-scope record may still support the factual assertion for UCR. |
| S2 says only “a successful acct-a logon on WS01 was recorded at 10:00.” S3 additionally says “a PowerShell process for acct-a was created on WS01 at 10:03,” citing `E-SYN-003`. | Under approved P-03 and P-05, S2 covers synthetic F-SYN-001 but omits F-SYN-002; S3 faithfully covers both. This illustrates omission checking without a computed CFR value or any use of evaluation gold by the operational S3 inventory. |
| S2 contains one unsupported “acct-a was compromised.” S3 repeats that unsupported proposition twice and adds “the compromise caused exfiltration.” | Under approved P-06 predecessor existence, the two equivalent repeats are not *introduced* but remain two unsupported S3 assertions; the new causal/exfiltration atom is introduced. UCR, absolute unsupported counts, citation counts, and length diagnostics remain separate. |

## 12. Quality assurance, versioning, approval gates, and acceptance

The project owner approved P-01 through P-08 and guideline v1.0 on 2026-10-15, recorded in D-009. W1-04 acceptance covers the rubric and procedure, **not** real gold production, agreement values, access-control implementation, split freeze, or experiment readiness. The written examples are synthetic and cannot enter the held-out pair manifest or gold set. Test/OOD labels, split IDs, prompts, metric definitions/denominators, and frozen fixtures remain protected; post-freeze changes require a versioned protocol amendment and human approval. Keep rejected or superseded rubric versions and reasons for reproducibility.

| Approved W1-04 decision | Operational rule | Main evaluation exposure |
| --- | --- | --- |
| P-01 | Atomic segmentation, hedged factual inferences and truthful evidence-limit statements (§2) | RQ1/RQ3 pair units; RQ2 UCR denominator |
| P-02 | S/C/I precedence and fixed-pair versus incident evidence/citation treatment (§4) | All support labels and errors; CSA interpretation |
| P-03 | High/medium/low criticality anchors, observability and eligibility (§6) | RQ2 CFR denominator |
| P-04 | Extra-citation relevance (§7) | RQ2 CSA; citation diagnostics |
| P-05 | Required attributes and fully/partial/ambiguous/not-covered decisions (§8) | RQ2 CFR numerator |
| P-06 | S2/S3 predecessor existence, duplicates and one-to-one alternative (§8) | RQ2 dilution diagnostics; emitted-claim occurrence lock |
| P-07 | Double annotation, blinding, adjudication and audit (§9) | Gold independence for all RQs |
| P-08 | Agreement statistic and reporting (§10) | Gold reliability interpretation |

Pre-scoring QA must check incident/tenant scope and evidence-snapshot identity, source provenance, fixed claim units and candidate populations, independent initial records, reasoned adjudications, blinding/access audit, actual double-coded counts, and schema validation. W1-07 must verify split/lineage manifests and sealed gold access; W7 must complete its method locks, calibration and audits before conditional held-out A/B evaluation. Do not inspect test/OOD outcomes to tune this rubric, choose examples, or set thresholds. Report unresolved cases and protocol deviations; do not silently repair denominators or suppress negative results.

**W1-04 documentation acceptance checklist:**

- [x] S/C/I meanings, atomization, uncertainty, precedence, review routing, and synthetic edge cases are documented as approved operational decisions.
- [x] Independent gold-fact procedure, criticality/observability/CFR eligibility, citation relevance, coverage and S2/S3 matching are documented with owner gates.
- [x] Independent annotation, disagreement, adjudication, agreement reporting, and W1-03 audit-metadata gap are documented.
- [x] Synthetic structured examples use only approved W1-03 model fields and keep evaluation gold separate from inference input.
- [x] Owner approved P-01–P-08 and guideline v1.0 on 2026-10-15 (D-009).
- [ ] Later custodians implement and audit the independent gold store, annotation records, split/freeze controls, and pretest gates; no completion is asserted here.
