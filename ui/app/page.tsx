"use client";

import { useEffect, useState } from "react";

// Every request goes to THIS origin. The browser never learns the service's address and never
// holds its credential; the route handler under /api/agent forwards, having discarded whatever
// identity the client tried to assert.
const API = "/api/agent";

// Mirrors the service's seeded local personas. The picker is a DEV convenience: the server
// validates the selection against its own list, so a hand-crafted value cannot invent a persona.
const PERSONAS = ["analyst", "approver", "auditor", "other-tenant"];

// What happened to the human-review hand-off, in the words the user needs. A result that
// escalated but is not queued must say so rather than read as reviewed.
const REVIEW_ROUTING_TEXT: Record<string, string> = {
  routed: "Sent to the review console.",
  failed: "Could not reach the review console; this case is not queued for review.",
  off: "Review routing is off in this deployment; this case is not queued for review.",
};

function reviewRoutingOf(body: string): string | undefined {
  try {
    const parsed = JSON.parse(body) as { review_routing?: unknown };
    return typeof parsed.review_routing === "string" ? parsed.review_routing : undefined;
  } catch {
    return undefined;
  }
}

// The feed sets the local profile's fixture serves (`adapters/local/_recon_fixture.py`): an
// obviously fictional nostro ledger and the scheme statement it is reconciled against. There is no
// listing endpoint, so they are offered as suggestions; any other name is sent as typed and a
// profile that does not serve it refuses the run.
const LOCAL_FEEDS = ["nostro", "scheme"];

// The fixture's fixed reconciliation instant. Aging is measured from it, so the default run replays
// byte for byte; clearing the date reconciles as at the server's today.
const ANCHOR_AS_OF = "2026-08-08";

// One ranked break, as `GET /v1/worklist/{worklist_id}` returns it.
interface RankedBreak {
  rank: number;
  score: number;
  break_id: string;
  break_type: string;
  currency: string;
  amount_minor: number;
  age_days: number;
  entry_ids: string[];
}

// The persisted, tenant-scoped worklist a reconcile run produced.
interface Worklist {
  worklist_id: string;
  feed_id: string;
  as_of: string;
  breaks: RankedBreak[];
}

function worklistText(worklist: Worklist): string {
  const head = `${worklist.worklist_id}: feeds ${worklist.feed_id}, as of ${worklist.as_of}`;
  if (worklist.breaks.length === 0) return head + "\nNo breaks: every entry matched.";
  const rows = worklist.breaks.map(
    (item) =>
      `#${item.rank}  score ${item.score}  ${item.break_type}  ${item.currency} ` +
      `${item.amount_minor} minor  aged ${item.age_days}d  ${item.break_id}  ` +
      `entries ${item.entry_ids.join(", ")}`,
  );
  return [head, ...rows].join("\n");
}

interface CardSummary {
  name?: string;
  description?: string;
  skills?: { id: string; name: string }[];
}

export default function Home() {
  const [persona, setPersona] = useState(PERSONAS[0]);
  const [feedA, setFeedA] = useState(LOCAL_FEEDS[0]);
  const [feedB, setFeedB] = useState(LOCAL_FEEDS[1]);
  const [asOf, setAsOf] = useState(ANCHOR_AS_OF);
  const [result, setResult] = useState("");
  const [worklist, setWorklist] = useState<Worklist | null>(null);
  const [worklistError, setWorklistError] = useState("");
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [card, setCard] = useState<CardSummary | null>(null);

  // The service names itself, so this UI carries no hardcoded product name to go stale.
  useEffect(() => {
    let live = true;
    fetch(API + "/.well-known/agent-card.json", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        if (live) setCard(body as CardSummary | null);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    setWorklist(null);
    setWorklistError("");
    try {
      const response = await fetch(API + "/v1/reconcile", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Dev-Persona": persona },
        body: JSON.stringify({ feed_a: feedA, feed_b: feedB, as_of: asOf }),
      });
      const body = await response.text();
      setFailed(!response.ok);
      setResult(body);
      if (!response.ok) return;
      // The run persisted its ranked worklist under a tenant-scoped handle; read it back through
      // the retrieval route, which authorizes the persona's own tenant, and show what was stored.
      const worklistId = (JSON.parse(body) as { worklist_id?: string }).worklist_id ?? "";
      if (!worklistId) {
        setWorklistError("The run returned no worklist id.");
        return;
      }
      const stored = await fetch(API + "/v1/worklist/" + encodeURIComponent(worklistId), {
        cache: "no-store",
        headers: { "X-Dev-Persona": persona },
      });
      if (stored.ok) setWorklist((await stored.json()) as Worklist);
      else setWorklistError(stored.status + " " + (await stored.text()));
    } catch (error) {
      setFailed(true);
      setResult(String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>{card?.name ?? "Agent console"}</h1>
      <p className="sub">
        {card?.description ??
          "Reconcile two feeds. Matching and ranking are deterministic, every break is cited, and each drafted resolution is routed to a human reviewer."}
      </p>

      <form onSubmit={submit}>
        <fieldset>
          <legend>Who you are</legend>
          <label>
            Seeded dev persona (local profile only; the server resolves identity, not this field)
            <select value={persona} onChange={(event) => setPersona(event.target.value)}>
              {PERSONAS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </fieldset>

        <fieldset>
          <legend>The feeds</legend>
          <datalist id="local-feeds">
            {LOCAL_FEEDS.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
          <label>
            Feed A (internal authority, e.g. the nostro ledger)
            <input list="local-feeds" value={feedA} onChange={(event) => setFeedA(event.target.value)} />
          </label>
          <label>
            Feed B (external, e.g. the scheme statement)
            <input list="local-feeds" value={feedB} onChange={(event) => setFeedB(event.target.value)} />
          </label>
          <label>
            As of (aging is measured from this date; leave empty for today)
            <input type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
          </label>
          <button type="submit" disabled={busy || !feedA || !feedB}>
            {busy ? "Working" : "Reconcile these feeds"}
          </button>
        </fieldset>
      </form>

      {result && REVIEW_ROUTING_TEXT[reviewRoutingOf(result) ?? ""] ? (
        <p className="sub" data-review-routing={reviewRoutingOf(result)}>
          {REVIEW_ROUTING_TEXT[reviewRoutingOf(result) ?? ""]}
        </p>
      ) : null}
      {worklistError ? (
        <pre className="result error">Could not read the stored worklist: {worklistError}</pre>
      ) : null}
      {worklist ? <pre className="result">{worklistText(worklist)}</pre> : null}
      {result && failed ? <pre className="result error">{result}</pre> : null}
      {result && !failed ? (
        <details>
          <summary>Full reconcile response: matches, drafted resolutions and the ops export</summary>
          <pre className="result">{result}</pre>
        </details>
      ) : null}

      <footer>
        Synthetic, obviously fictional data only. Identity is resolved server-side and the
        client-asserted actor is discarded; see ui/README.md for the embedding contract.
      </footer>
    </main>
  );
}
