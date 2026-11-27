// End-to-end check of the web app's live partner code (firestorePartners in
// web/index.html) against the security rules on the Firestore emulator: the
// queries and writes the app really makes must be allowed, in order.
import { readFileSync } from "node:fs";
import { initializeTestEnvironment } from "@firebase/rules-unit-testing";
import * as fs from "firebase/firestore";
import { pairId } from "../../web/partners.js";

const html = readFileSync(new URL("../../web/index.html", import.meta.url), "utf8");
const start = html.indexOf("function firestorePartners(");
const end = html.indexOf("\n}\n", start) + 2;
const firestorePartners = new Function("pairId", `${html.slice(start, end)}; return firestorePartners;`)(pairId);

const env = await initializeTestEnvironment({
  projectId: "demo-flow",
  firestore: { rules: readFileSync(new URL("../../firestore.rules", import.meta.url), "utf8"), host: "127.0.0.1", port: 8080 },
});
const as = (uid) => firestorePartners(fs, env.authenticatedContext(uid).firestore(), { uid });
const ana = as("ana"), bia = as("bia");
const card = { ufs: ["SP"], kinds: ["apartamento"], modalities: [], price_min: 1e5, price_max: 5e5, ticket_min: 5e4, ticket_max: 1e5, goal: "revenda" };
let n = 0, failed = 0;
async function step(name, fn) { n++; try { await fn(); } catch (e) { failed++; console.log("FAIL", name, "-", e.message.split("\n")[0]); } }
const expect = (c, msg) => { if (!c) throw new Error(msg); };

await step("both opt in", async () => { await ana.saveCard(card); await bia.saveCard(card); await bia.saveContact({ name: "Bia", email: "bia@x.com" }); });
await step("ana browses cards", async () => expect((await ana.cards()).some((c) => c.uid === "bia"), "bia's card not listed"));
await step("contact hidden before connecting", async () => expect((await ana.contactOf("bia")) === null, "contact leaked"));
await step("ana invites bia", () => ana.invite("bia", "Oi"));
await step("bia sees the invite", async () => expect((await bia.connections()).some((c) => c.status === "pending" && c.to === "bia"), "no invite"));
await step("bia accepts", () => bia.respond(pairId("ana", "bia"), true));
await step("ana now sees bia's contact", async () => expect((await ana.contactOf("bia"))?.email === "bia@x.com", "contact missing"));
let gid;
await step("ana creates a public group", async () => { gid = await ana.createGroup({ name: "Apto Moema", description: "", visibility: "public", quota_min: 5e4, quota_max: 2e5, max_members: 3, target_title: "", target_url: "", target_price: 4e5 }, { quota: 1e5, name: "Ana", contact: "ana@x.com" }); });
await step("bia lists public groups", async () => expect((await bia.publicGroups()).some((g) => g.id === gid), "group not listed"));
await step("bia applies", () => bia.apply(gid, { quota: 6e4, name: "Bia", contact: "bia@x.com" }));
await step("bia's memberships", async () => expect((await bia.memberships()).some((m) => m.gid === gid && m.status === "applied"), "membership missing"));
await step("leader lists all members", async () => expect((await ana.members(gid, true)).length === 2, "leader should see 2"));
await step("leader approves", async () => { const g = await ana.group(gid); await ana.approve(gid, "bia", g.member_count); });
await step("bia lists approved members", async () => expect((await bia.members(gid, false)).length === 2, "member should see 2"));
await step("bia changes quota", () => bia.setQuota(gid, 9e4));
await step("bia leaves", async () => { const g = await bia.group(gid); await bia.leave(gid, true, g.member_count); expect((await ana.group(gid)).member_count === 1, "count not decremented"); });
let pg;
await step("private group + invite + accept", async () => {
  pg = await ana.createGroup({ name: "Privado", description: "", visibility: "private", quota_min: 5e4, quota_max: 2e5, max_members: 2, target_title: "", target_url: "", target_price: null }, { quota: 1e5, name: "Ana", contact: "ana@x.com" });
  await ana.inviteToGroup(pg, "bia");
  const g = await bia.group(pg);
  await bia.acceptGroupInvite(pg, { quota: 1e5, name: "Bia", contact: "bia@x.com" }, g.member_count);
  expect((await ana.group(pg)).member_count === 2, "count not incremented");
});
await step("leader closes both groups", async () => {
  for (const id of [gid, pg]) { const m = await ana.members(id, true); await ana.closeGroup(id, m.map((x) => x.uid)); }
  expect((await bia.memberships()).length === 0, "memberships left behind");
});
await step("bia hides her card", () => bia.deleteCard());
await step("disconnect", () => ana.removeConnection(pairId("ana", "bia")));

console.log(`${n - failed}/${n} app flow steps passed`);
await env.cleanup();
process.exit(failed ? 1 : 0);
