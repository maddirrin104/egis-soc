"use strict";
const byId = (id) => document.getElementById(id);
const node = (tag, value) => { const n = document.createElement(tag); n.textContent = value == null ? "" : String(value); return n; };
const card = (parent, title, value) => { const a = node("article", ""); a.append(node("h3", title), node("pre", JSON.stringify(value, null, 2))); parent.append(a); };
const clear = (...ids) => ids.forEach((id) => byId(id).replaceChildren());
let report = null;
let reviewToken = null;
let reviewSnapshot = null;

async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (reviewToken) headers.Authorization = "Bearer " + reviewToken;
  const response = await fetch(path, {...options, headers, cache:"no-store"});
  if (response.status === 401 && reviewToken) {
    resetReviewSession();
    byId("authStatus").textContent = "Review session expired. Sign in again.";
  }
  if (!response.ok) throw new Error("Request failed: " + response.status);
  return response.json();
}

function reviewPath(suffix = "") {
  return "/api/reviews/" + encodeURIComponent(report.incident_id) + suffix;
}

function resetReviewSession() {
  reviewToken = null;
  reviewSnapshot = null;
  byId("logout").hidden = true;
  byId("reviewPanel").hidden = true;
  byId("reviewState").textContent = "";
  clear("audit");
}

async function loadReview() {
  if (!report || !reviewToken) { byId("reviewPanel").hidden = true; return; }
  try {
    reviewSnapshot = await api(reviewPath());
    const events = await api(reviewPath("/audit"));
    byId("reviewPanel").hidden = false;
    byId("reviewVersion").textContent = `Report ${reviewSnapshot.report_id}, version ${reviewSnapshot.report_version}, parent ${reviewSnapshot.parent_version ?? "none"}; ${reviewSnapshot.review.status}; gold ${reviewSnapshot.gold_status}.`;
    byId("reviewState").textContent = JSON.stringify(reviewSnapshot.review, null, 2);
    clear("audit", "reviewClaim");
    byId("reviewClaim").append(new Option("Report-wide", ""));
    for (const claim of [...report.final_claims, ...report.draft_candidates]) {
      if (![...byId("reviewClaim").options].some((option) => option.value === claim.claim_id)) {
        byId("reviewClaim").append(new Option(`${claim.claim_id}: ${claim.prediction || "pending"}`, claim.claim_id));
      }
    }
    for (const event of events) card(byId("audit"), `${event.sequence}: ${event.action}`, event);
    if (!events.length) byId("audit").append(node("p", "No review actions recorded."));
  } catch (error) { byId("reviewStatus").textContent = error.message; }
}

async function run() {
  byId("status").textContent = "Running fixed synthetic pipeline...";
  byId("packet").hidden = true;
  try {
    report = await api("/api/run", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({case:byId("case").value})});
    clear("warnings", "overview", "timeline", "final", "draft", "omissions", "repair", "queue", "evidence");
    byId("scope").textContent = `${report.incident_id} / ${report.tenant_id}; ${report.w8_demo.mode}; ${report.w8_demo.model_trace_id_note}; gold ${report.gold_status}.`;
    for (const warning of report.warnings) byId("warnings").append(node("li", warning));
    byId("overview").textContent = report.structured_report.incident_overview || "No verified free-text overview; inspect the claims below.";
    for (const claim of report.final_claims) card(byId("final"), `${claim.claim_id}: ${claim.prediction}`, claim);
    if (!report.final_claims.length) byId("final").append(node("p", "No verified final claims."));
    for (const claim of report.draft_candidates) card(byId("draft"), `${claim.claim_id}: ${claim.prediction || "unassessed"} / ${claim.s2_action}`, claim);
    for (const item of report.omission_findings) card(byId("omissions"), `${item.fact_id}: ${item.outcome}`, item);
    for (const item of report.repair_history) card(byId("repair"), `Round ${item.round}: ${item.action} / ${item.result}`, item);
    for (const item of report.review_queue) card(byId("queue"), item.reason, item);
    for (const item of report.evidence) card(byId("evidence"), item.evidence_id, item);
    const events = [...report.evidence].sort((a,b) => a.timestamp_utc.localeCompare(b.timestamp_utc));
    for (const item of events) byId("timeline").append(node("p", `${item.timestamp_utc}: ${item.evidence_id} (${item.source})`));
    byId("structured").textContent = JSON.stringify(report.structured_report, null, 2);
    byId("export").href = "/api/export/" + encodeURIComponent(report.incident_id);
    byId("export").hidden = false;
    byId("packet").hidden = false;
    byId("status").textContent = "Synthetic pipeline complete. Analyst review is separate from evaluation gold.";
    await loadReview();
  } catch (error) { byId("status").textContent = error.message; }
}

async function login() {
  try {
    const password = byId("password").value;
    const result = await api("/api/login", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({password})});
    byId("password").value = "";
    reviewToken = result.token;
    byId("logout").hidden = false;
    byId("authStatus").textContent = `Signed in as ${result.reviewer_id}; session expires in ${result.expires_in_seconds} seconds.`;
    await loadReview();
  } catch (error) { byId("password").value = ""; byId("authStatus").textContent = error.message; }
}

async function logout() {
  try { if (reviewToken) await api("/api/logout", {method:"POST"}); }
  catch (error) { /* Local state is cleared even if the session expired. */ }
  resetReviewSession();
  byId("authStatus").textContent = "Signed out. Read-only synthetic demo.";
}

async function submitReview() {
  if (!report || !reviewSnapshot || !reviewToken) return;
  const action = byId("reviewAction").value;
  const claimAction = ["accept_claim", "reject_claim", "request_claim_changes"].includes(action);
  const claim_id = claimAction || action === "note" ? byId("reviewClaim").value || null : null;
  const payload = {action, claim_id, reason:byId("reviewReason").value.trim(),
                   expected_version:reviewSnapshot.report_version};
  try {
    const result = await api(reviewPath("/actions"), {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
    byId("reviewReason").value = "";
    byId("reviewStatus").textContent = `Recorded ${result.audit_record.audit_record_id}; version ${result.snapshot.report_version}.`;
    await loadReview();
  } catch (error) { byId("reviewStatus").textContent = error.message; }
}

async function exportReviewed() {
  if (!report || !reviewToken) return;
  try {
    const data = await api(reviewPath("/export"));
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type:"application/json"}));
    const link = document.createElement("a");
    link.href = url;
    link.download = report.incident_id + "-reviewed-synthetic.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { byId("reviewStatus").textContent = error.message; }
}

byId("run").addEventListener("click", run);
byId("login").addEventListener("click", login);
byId("logout").addEventListener("click", logout);
byId("reviewSubmit").addEventListener("click", submitReview);
byId("reviewExport").addEventListener("click", exportReviewed);
