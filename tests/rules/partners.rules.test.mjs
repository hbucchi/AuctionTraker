// Security-rule tests for partners and groups, run against the Firestore emulator:
//   cd tests/rules && npm i && npx firebase emulators:exec --only firestore --project demo-at "node partners.rules.test.mjs"
// Each case acts as a specific signed-in user and asserts the database allows
// or refuses the operation, so the privacy promises hold even for someone
// calling the database directly instead of using the app.
import { readFileSync } from "node:fs";
import { initializeTestEnvironment, assertFails, assertSucceeds } from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc, updateDoc, deleteDoc, writeBatch, collection, query, where, getDocs, collectionGroup } from "firebase/firestore";

const env = await initializeTestEnvironment({
  projectId: "demo-at",
  firestore: { rules: readFileSync(new URL("../../firestore.rules", import.meta.url), "utf8"), host: "127.0.0.1", port: 8080 },
});
const dbs = {};
const db = (uid) => (dbs[uid] ??= env.authenticatedContext(uid).firestore());
const anon = env.unauthenticatedContext().firestore();
const pair = (a, b) => (a < b ? `${a}_${b}` : `${b}_${a}`);
const card = { ufs: ["SP"], kinds: ["apartamento"], modalities: [], price_min: 100000, price_max: 500000, ticket_min: 50000, ticket_max: 100000, goal: "revenda" };
let n = 0, failed = 0;
async function t(name, fn) {
  n++;
  try { await fn(); } catch (e) { failed++; console.log("FAIL", name, "-", e.message.split("\n")[0]); }
}
async function seed(fn) { await env.withSecurityRulesDisabled(async (ctx) => fn(ctx.firestore())); }

// ---------------------------------------------------------------- cards
await t("can't browse cards without opting in", () => assertFails(getDoc(doc(db("ana"), "partner_cards/bia"))));
await t("opt in with an anonymous card", () => assertSucceeds(setDoc(doc(db("ana"), "partner_cards/ana"), card)));
await t("a card can't carry a name or email", () => assertFails(setDoc(doc(db("ana"), "partner_cards/ana"), { ...card, email: "ana@x.com" })));
await t("can't write someone else's card", () => assertFails(setDoc(doc(db("ana"), "partner_cards/bia"), card)));
await seed((f) => Promise.all(["bia", "caio", "duda", "eva"].map((u) => setDoc(doc(f, `partner_cards/${u}`), card))));
await t("opted-in users browse cards", () => assertSucceeds(getDoc(doc(db("ana"), "partner_cards/bia"))));
await t("signed-out visitors see nothing", () => assertFails(getDoc(doc(anon, "partner_cards/bia"))));

// ---------------------------------------------------------------- contacts + connections
await seed((f) => setDoc(doc(f, "contacts/bia"), { name: "Bia", email: "bia@x.com" }));
await t("contact hidden before any connection", () => assertFails(getDoc(doc(db("ana"), "contacts/bia"))));
const inv = { users: ["ana", "bia"], from: "ana", to: "bia", status: "pending", note: "Oi" };
await t("invite with a forged sender is refused", () => assertFails(setDoc(doc(db("caio"), `connections/${pair("ana", "bia")}`), inv)));
await t("invite already 'accepted' is refused", () => assertFails(setDoc(doc(db("ana"), `connections/${pair("ana", "bia")}`), { ...inv, status: "accepted" })));
await t("invite someone without a card is refused", () => assertFails(setDoc(doc(db("ana"), `connections/${pair("ana", "zed")}`), { ...inv, to: "zed", users: ["ana", "zed"] })));
await t("send an invite", () => assertSucceeds(setDoc(doc(db("ana"), `connections/${pair("ana", "bia")}`), inv)));
await t("sender can't accept their own invite", () => assertFails(updateDoc(doc(db("ana"), `connections/${pair("ana", "bia")}`), { status: "accepted" })));
await t("outsider can't read the invite", () => assertFails(getDoc(doc(db("caio"), `connections/${pair("ana", "bia")}`))));
await t("contact still hidden while pending", () => assertFails(getDoc(doc(db("ana"), "contacts/bia"))));
await t("invitee accepts", () => assertSucceeds(updateDoc(doc(db("bia"), `connections/${pair("ana", "bia")}`), { status: "accepted" })));
await t("now the contact is visible", () => assertSucceeds(getDoc(doc(db("ana"), "contacts/bia"))));
await t("…but not to anyone else", () => assertFails(getDoc(doc(db("caio"), "contacts/bia"))));
await t("my connections query", () => assertSucceeds(getDocs(query(collection(db("ana"), "connections"), where("users", "array-contains", "ana")))));
await t("declined invite can't be resent", async () => {
  await assertSucceeds(setDoc(doc(db("caio"), `connections/${pair("caio", "duda")}`), { users: ["caio", "duda"], from: "caio", to: "duda", status: "pending" }));
  await assertSucceeds(updateDoc(doc(db("duda"), `connections/${pair("caio", "duda")}`), { status: "declined" }));
  await assertFails(deleteDoc(doc(db("caio"), `connections/${pair("caio", "duda")}`)));
  await assertFails(setDoc(doc(db("caio"), `connections/${pair("caio", "duda")}`), { users: ["caio", "duda"], from: "caio", to: "duda", status: "pending" }));
});

// ---------------------------------------------------------------- groups
const g = { name: "Apto Moema", description: "", visibility: "public", leader: "ana", quota_min: 50000, quota_max: 200000, max_members: 3, member_count: 1 };
async function createGroup(gid, data, quota = 100000) {
  const b = writeBatch(db(data.leader));
  b.set(doc(db(data.leader), `groups/${gid}`), data);
  b.set(doc(db(data.leader), `groups/${gid}/members/${data.leader}`), { uid: data.leader, role: "leader", status: "approved", quota, name: "Ana", contact: "ana@x.com" });
  return b.commit();
}
await t("leader creates a public group", () => assertSucceeds(createGroup("g1", g)));
await t("quota range must be valid", () => assertFails(createGroup("gbad", { ...g, quota_min: 300000 })));
await t("can't create a group as someone else", () => assertFails(setDoc(doc(db("bia"), "groups/g2"), { ...g, leader: "ana" })));
await t("public groups are listed", () => assertSucceeds(getDocs(query(collection(db("caio"), "groups"), where("visibility", "==", "public")))));
const apply = (uid, quota) => setDoc(doc(db(uid), `groups/g1/members/${uid}`), { uid, role: "member", status: "applied", quota, name: uid, contact: `${uid}@x.com` });
await t("apply below the minimum quota is refused", () => assertFails(apply("bia", 10000)));
await t("apply already 'approved' is refused", () => assertFails(setDoc(doc(db("bia"), "groups/g1/members/bia"), { uid: "bia", role: "member", status: "approved", quota: 100000 })));
await t("apply as leader role is refused", () => assertFails(setDoc(doc(db("bia"), "groups/g1/members/bia"), { uid: "bia", role: "leader", status: "approved", quota: 100000 })));
await t("apply within the range", () => assertSucceeds(apply("bia", 80000)));
await t("applicant can't approve themselves", () => assertFails(updateDoc(doc(db("bia"), "groups/g1/members/bia"), { status: "approved" })));
await t("leader sees the applicant", () => assertSucceeds(getDoc(doc(db("ana"), "groups/g1/members/bia"))));
await t("another applicant can't see the first", async () => { await assertSucceeds(apply("caio", 60000)); await assertFails(getDoc(doc(db("caio"), "groups/g1/members/bia"))); });
const approve = (uid, count) => { const b = writeBatch(db("ana")); b.update(doc(db("ana"), `groups/g1/members/${uid}`), { status: "approved" }); b.update(doc(db("ana"), "groups/g1"), { member_count: count }); return b.commit(); };
await t("approval must count the new member", () => assertFails(updateDoc(doc(db("ana"), "groups/g1/members/bia"), { status: "approved" })));
await t("leader approves (2/3)", () => assertSucceeds(approve("bia", 2)));
await t("approved members see each other", () => assertSucceeds(getDoc(doc(db("bia"), "groups/g1/members/ana"))));
await t("…but not pending applicants", () => assertFails(getDoc(doc(db("bia"), "groups/g1/members/caio"))));
await t("members list approved members", () => assertSucceeds(getDocs(query(collection(db("bia"), "groups/g1/members"), where("status", "==", "approved")))));
await t("member raises quota within range", () => assertSucceeds(updateDoc(doc(db("bia"), "groups/g1/members/bia"), { quota: 150000 })));
await t("member can't exceed the maximum", () => assertFails(updateDoc(doc(db("bia"), "groups/g1/members/bia"), { quota: 900000 })));
await t("leader approves (3/3)", () => assertSucceeds(approve("caio", 3)));
await t("no approval beyond the member limit", async () => { await assertSucceeds(apply("duda", 60000)); await assertFails(approve("duda", 4)); });
await t("a member can't take over the group", () => assertFails(updateDoc(doc(db("bia"), "groups/g1"), { leader: "bia" })));
await t("a member can't bump the count alone", () => assertFails(updateDoc(doc(db("bia"), "groups/g1"), { member_count: 2 })));
await t("member leaves (count -1 with it)", () => {
  const b = writeBatch(db("caio")); b.delete(doc(db("caio"), "groups/g1/members/caio")); b.update(doc(db("caio"), "groups/g1"), { member_count: 2 }); return assertSucceeds(b.commit());
});
await t("the leader can't just leave", () => assertFails(deleteDoc(doc(db("ana"), "groups/g1/members/ana"))));
await t("a member can't remove another member", () => assertFails(deleteDoc(doc(db("bia"), "groups/g1/members/duda"))));
await t("leader closes the group with all memberships", () => {
  const b = writeBatch(db("ana"));
  for (const u of ["ana", "bia", "duda"]) b.delete(doc(db("ana"), `groups/g1/members/${u}`));
  b.delete(doc(db("ana"), "groups/g1"));
  return assertSucceeds(b.commit());
});

// private group: invite-only
await t("leader creates a private group", () => assertSucceeds(createGroup("g3", { ...g, visibility: "private", max_members: 2 })));
await t("outsiders can't see a private group", () => assertFails(getDoc(doc(db("eva"), "groups/g3"))));
await t("no applying to a private group", () => assertFails(setDoc(doc(db("eva"), "groups/g3/members/eva"), { uid: "eva", role: "member", status: "applied", quota: 100000 })));
const invite = (uid) => setDoc(doc(db("ana"), `groups/g3/members/${uid}`), { uid, role: "member", status: "invited", quota: null, name: null, contact: null });
await t("only the leader invites", () => assertFails(setDoc(doc(db("bia"), "groups/g3/members/eva"), { uid: "eva", role: "member", status: "invited", quota: null, name: null, contact: null })));
await t("can't invite someone who neither opted in nor connected", () => assertFails(invite("zed")));
await t("leader invites an opted-in investor", () => assertSucceeds(invite("eva")));
await t("the invitee now sees the group", () => assertSucceeds(getDoc(doc(db("eva"), "groups/g3"))));
await t("my groups and invites (collection group)", () => assertSucceeds(getDocs(query(collectionGroup(db("eva"), "members"), where("uid", "==", "eva")))));
const accept = (uid, quota, count) => { const b = writeBatch(db(uid)); b.update(doc(db(uid), `groups/g3/members/${uid}`), { status: "approved", quota, name: uid, contact: "x" }); b.update(doc(db(uid), "groups/g3"), { member_count: count }); return b.commit(); };
await t("invitee can't accept with a quota out of range", () => assertFails(accept("eva", 1, 2)));
await t("invitee accepts (2/2)", () => assertSucceeds(accept("eva", 100000, 2)));
await t("invitee can't join a full group", async () => { await assertSucceeds(invite("duda")); await assertFails(accept("duda", 100000, 3)); });
await t("invitee declines by deleting their invite", () => assertSucceeds(deleteDoc(doc(db("duda"), "groups/g3/members/duda"))));

// ---------------------------------------------------------------- contract terms
await t("leader saves contract terms", async () => { await createGroup("g4", { ...g, max_members: 3 }); await assertSucceeds(updateDoc(doc(db("ana"), "groups/g4"), { deal: { max_bid: 400000, version: 1 } })); });
await t("terms must be a map", () => assertFails(updateDoc(doc(db("ana"), "groups/g4"), { deal: "anything" })));
await seed((f) => setDoc(doc(f, "groups/g4/members/bia"), { uid: "bia", role: "member", status: "approved", quota: 60000, name: "Bia", contact: "b" }));
await seed((f) => updateDoc(doc(f, "groups/g4"), { member_count: 2 }));
await t("a member can't change the terms", () => assertFails(updateDoc(doc(db("bia"), "groups/g4"), { deal: { max_bid: 9e9, version: 2 } })));
await t("a member agrees to a version", () => assertSucceeds(updateDoc(doc(db("bia"), "groups/g4/members/bia"), { agreed_version: 1 })));
await t("agreement must be a number", () => assertFails(updateDoc(doc(db("bia"), "groups/g4/members/bia"), { agreed_version: "yes" })));
await t("nobody agrees on someone else's behalf", () => assertFails(updateDoc(doc(db("ana"), "groups/g4/members/bia"), { agreed_version: 1 })));

// ---------------------------------------------------------------- professionals
const pro = { name: "Ana Advocacia", category: "advogado", uf: "SP", cities: "São Paulo", description: "Leilões", phone: "11", email: "a@x.com", site: "", registration: "OAB", status: "pending" };
await t("apply to be listed (pending)", () => assertSucceeds(setDoc(doc(db("ana"), "pros/ana"), pro)));
await t("can't list yourself as approved", () => assertFails(setDoc(doc(db("ana"), "pros/ana"), { ...pro, status: "approved" })));
await t("can't create someone else's listing", () => assertFails(setDoc(doc(db("bia"), "pros/ana"), pro)));
await t("unknown category refused", () => assertFails(setDoc(doc(db("ana"), "pros/ana"), { ...pro, category: "astrologo" })));
await t("pending listing hidden from others", () => assertFails(getDoc(doc(db("bia"), "pros/ana"))));
await t("owner sees own pending listing", () => assertSucceeds(getDoc(doc(db("ana"), "pros/ana"))));
await t("non-admin can't approve", () => assertFails(updateDoc(doc(db("bia"), "pros/ana"), { status: "approved" })));
await t("nobody makes themselves admin", () => assertFails(setDoc(doc(db("bia"), "admins/bia"), { since: 1 })));
await seed((f) => setDoc(doc(f, "admins/caio"), { since: 1 }));
await t("admin sees pending listings", () => assertSucceeds(getDocs(query(collection(db("caio"), "pros"), where("status", "==", "pending")))));
await t("admin approves", () => assertSucceeds(updateDoc(doc(db("caio"), "pros/ana"), { status: "approved" })));
await t("admin can't edit the listing's content", () => assertFails(updateDoc(doc(db("caio"), "pros/ana"), { phone: "000" })));
await t("approved listing visible to signed-in users", () => assertSucceeds(getDocs(query(collection(db("bia"), "pros"), where("status", "==", "approved")))));
await t("…not to signed-out visitors", () => assertFails(getDoc(doc(anon, "pros/ana"))));
await t("editing sends it back to review", async () => { await assertFails(updateDoc(doc(db("ana"), "pros/ana"), { phone: "22" })); await assertSucceeds(setDoc(doc(db("ana"), "pros/ana"), { ...pro, phone: "22", status: "pending" })); });

console.log(`${n - failed}/${n} rule checks passed`);
await env.cleanup();
process.exit(failed ? 1 : 0);
