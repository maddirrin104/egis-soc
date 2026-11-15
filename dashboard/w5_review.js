"use strict";

const byId = (id) => document.getElementById(id);
const node = (tag, text) => {
  const item = document.createElement(tag);
  item.textContent = text == null ? "" : String(text);
  return item;
};
const addRecord = (parent, title, value) => {
  const card = node("article", "");
  card.append(node("h3", title), node("pre", JSON.stringify(value, null, 2)));
  parent.append(card);
};
let report = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Authorization": "Bearer " + byId("token").value,
               ...(options.headers || {}) },
    cache: "no-store",
  });
  if (!response.ok) throw new Error("Request failed: " + response.status);
  return response.json();
}

async function load() {
  try {
    report = await api("/api/report");
    byId("packet").hidden = false;
    byId("scope").textContent = `Incident ${report.incident_id}, tenant ${report.tenant_id}; S3 ${report.stage_status.s3}; gold ${report.gold_status}; analyst review separate.`;
    byId("structured").textContent = JSON.stringify(report.structured_report, null, 2);
    for (const key of ["warnings", "final", "candidates", "omissions", "history", "queue", "evidence"]) byId(key).replaceChildren();
    for (const warning of report.warnings) byId("warnings").append(node("li", warning));
    for (const claim of report.final_claims) addRecord(byId("final"), claim.claim_id, claim);
    if (!report.final_claims.length) byId("final").append(node("p", "No verified final claims; analyst review required."));
    for (const claim of report.draft_candidates) addRecord(byId("candidates"), claim.claim_id, claim);
    for (const finding of report.omission_findings) addRecord(byId("omissions"), finding.fact_id, finding);
    for (const item of report.repair_history) addRecord(byId("history"), `Round ${item.round}, action ${item.action_index}`, item);
    for (const item of report.review_queue) addRecord(byId("queue"), item.reason, item);
    for (const item of report.evidence) addRecord(byId("evidence"), item.evidence_id, item);
    await loadReviews();
    byId("status").textContent = "Packet loaded. No approval is inferred.";
  } catch (error) { byId("status").textContent = error.message; }
}

async function loadReviews() {
  const events = await api("/api/reviews");
  byId("reviews").replaceChildren();
  for (const event of events) addRecord(byId("reviews"), `${event.sequence}: ${event.action}`, event);
  if (!events.length) byId("reviews").append(node("p", "No review actions recorded."));
}

async function submit() {
  if (!report) return;
  const action = byId("action").value;
  const payload = {
    reviewer_id: byId("reviewer").value,
    action,
    claim_id: action === "correction" ? byId("claim").value : null,
    text: byId("text").value,
    confirm_approval: action === "approve" && byId("confirm").checked,
  };
  try {
    await api("/api/reviews", { method: "POST", headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify(payload) });
    byId("text").value = "";
    byId("confirm").checked = false;
    await loadReviews();
    byId("status").textContent = "Review action recorded separately from automated output.";
  } catch (error) { byId("status").textContent = error.message; }
}

byId("load").addEventListener("click", load);
byId("submit").addEventListener("click", submit);
