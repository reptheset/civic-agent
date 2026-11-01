"use client";
/* eslint-disable @typescript-eslint/no-explicit-any, @next/next/no-img-element */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

const API = "http://localhost:8000";
const WS = "ws://localhost:8000";

type Ev = { type: string; message: string; data: any; ts: number };

const TYPE_STYLE: Record<string, string> = {
  node: "bg-indigo-50 text-indigo-900 border-indigo-200 font-medium",
  observe: "bg-slate-50 text-slate-600 border-slate-200",
  decide: "bg-sky-50 text-sky-900 border-sky-200",
  act: "bg-white text-slate-700 border-slate-200",
  verify: "bg-emerald-50 text-emerald-800 border-emerald-200",
  recover: "bg-amber-50 text-amber-900 border-amber-300",
  security: "bg-rose-50 text-rose-900 border-rose-300 font-medium",
  interrupt: "bg-violet-50 text-violet-900 border-violet-300 font-medium",
  receipt: "bg-emerald-100 text-emerald-900 border-emerald-300 font-medium",
  error: "bg-red-50 text-red-800 border-red-300",
  log: "bg-white text-slate-500 border-slate-200",
  done: "bg-slate-800 text-white border-slate-800",
};

const BTN = "rounded px-3 py-2 text-sm font-medium disabled:opacity-40";

function Card({ title, children, highlight }: { title: string; children: ReactNode; highlight?: boolean }) {
  return (
    <div className={`rounded-lg bg-white p-4 shadow-sm border ${highlight ? "border-violet-400 ring-2 ring-violet-200" : "border-slate-200"}`}>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      {children}
    </div>
  );
}

function SourceBadge({ source, confidence }: { source: string; confidence?: number }) {
  const doc = source.startsWith("document");
  return (
    <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium ${doc ? "bg-indigo-100 text-indigo-800" : "bg-slate-200 text-slate-700"}`}>
      {source}{confidence !== undefined && doc ? ` · ${confidence.toFixed(2)}` : ""}
    </span>
  );
}

function EventRow({ ev, t0 }: { ev: Ev; t0?: number }) {
  const failed = ev.type === "verify" && ev.data?.ok === false;
  const style = failed ? "bg-red-50 text-red-800 border-red-300" : TYPE_STYLE[ev.type] ?? TYPE_STYLE.log;
  return (
    <div className={`rounded border px-2.5 py-1.5 text-sm ${style}`}>
      <div className="flex gap-2">
        <span className="w-20 shrink-0 pt-0.5 font-mono text-[10px] uppercase tracking-wide opacity-70">{ev.type}{t0 !== undefined && <span className="block normal-case">+{Math.round(ev.ts - t0)}s</span>}</span>
        <span className="break-words">{ev.message}</span>
      </div>
      {ev.type === "security" && Array.isArray(ev.data?.flagged) && (
        <ul className="ml-[5.5rem] mt-1 list-disc text-xs">
          {ev.data.flagged.map((f: string, i: number) => <li key={i}>removed: {f.slice(0, 140)}</li>)}
        </ul>
      )}
    </div>
  );
}

// ---------- Pause screens ----------

function ConfirmProfile({ data, onRespond }: { data: any; onRespond: (v: any) => void }) {
  const fields: any[] = data.fields ?? [];
  const mismatches: any[] = data.mismatches ?? [];
  const missing: any[] = data.missing ?? [];
  const check: string[] = Array.from(new Set([...(data.uncertain ?? []), ...mismatches.map((m) => m.field)]));
  const [vals, setVals] = useState<Record<string, string>>({});
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const ready = check.every((k) => accepted[k] || (vals[k] ?? "").trim());

  function submit() {
    const values: Record<string, string> = {};
    for (const k of check) values[k] = accepted[k] ? fields.find((f) => f.key === k)?.value ?? "" : vals[k];
    for (const m of missing) if ((vals[m.key] ?? "").trim()) values[m.key] = vals[m.key].trim();
    onRespond({ values });
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="mb-1 text-sm font-semibold">Read from your documents</h3>
        <table className="w-full text-sm">
          <tbody>
            {fields.filter((f) => !check.includes(f.key)).map((f) => (
              <tr key={f.key} className="border-t border-slate-100">
                <td className="py-1 pr-2 text-xs text-slate-500">{f.key}</td>
                <td className="py-1 pr-2 font-medium">{f.value}</td>
                <td className="py-1 text-right"><SourceBadge source={f.source} confidence={f.confidence} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {check.length > 0 && (
        <div className="rounded border border-amber-300 bg-amber-50 p-3">
          <h3 className="text-sm font-semibold text-amber-900">Please check these ({check.length})</h3>
          <p className="mb-2 text-xs text-amber-800">
            The agent could not confirm these against the document text. Compare with your document before accepting.
          </p>
          {check.map((k) => {
            const f = fields.find((x) => x.key === k);
            const mm = mismatches.find((m) => m.field === k);
            return (
              <div key={k} className="mb-3">
                <div className="text-xs font-semibold">{k}</div>
                {mm ? (
                  <div className="text-xs text-amber-900">
                    Documents disagree:{" "}
                    {Object.entries(mm.values as Record<string, string>).map(([d, v]) => `${d}: "${v}"`).join("  vs  ")}
                  </div>
                ) : (
                  <div className="text-xs">
                    Extracted: <b>{f?.value}</b> <span className="opacity-70">({f?.source}, confidence {f?.confidence})</span>
                  </div>
                )}
                <div className="mt-1 flex items-center gap-2">
                  <input
                    disabled={!!accepted[k]}
                    placeholder="Type the correct value"
                    value={vals[k] ?? ""}
                    onChange={(e) => setVals({ ...vals, [k]: e.target.value })}
                    className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-100"
                  />
                  {!mm && (
                    <label className="flex items-center gap-1 text-xs">
                      <input type="checkbox" checked={!!accepted[k]}
                        onChange={(e) => setAccepted({ ...accepted, [k]: e.target.checked })} />
                      Extracted value is correct
                    </label>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {missing.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold">Not on your documents</h3>
          {missing.map((m) => (
            <div key={m.key} className="mb-2">
              <label className="text-xs font-medium text-slate-600">{m.label}</label>
              {m.options ? (
                <select value={vals[m.key] ?? ""} onChange={(e) => setVals({ ...vals, [m.key]: e.target.value })}
                  className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-sm">
                  <option value="">— select —</option>
                  {m.options.map((o: string) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input value={vals[m.key] ?? ""} onChange={(e) => setVals({ ...vals, [m.key]: e.target.value })}
                  className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-sm" />
              )}
            </div>
          ))}
          <p className="text-xs text-slate-500">Leave blank to skip; the agent will ask if a form needs it.</p>
        </div>
      )}

      <button disabled={!ready} onClick={submit} className={`${BTN} w-full bg-indigo-600 text-white`}>
        Confirm details
      </button>
    </div>
  );
}

function Eligibility({ data, onRespond }: { data: any; onRespond: (v: any) => void }) {
  const g = data.guideline ?? {};
  const verdictStyle: Record<string, string> = {
    eligible: "bg-emerald-600", not_eligible: "bg-red-600", needs_review: "bg-amber-500",
  };
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-semibold uppercase text-white ${verdictStyle[data.verdict] ?? "bg-slate-500"}`}>
          {String(data.verdict).replace("_", " ")}
        </span>
        <span className="text-sm font-medium">{g.name}</span>
      </div>
      <p className="text-xs text-slate-500">
        Rules read live from{" "}
        <a href={g.url} target="_blank" rel="noreferrer" className="underline">{g.url}</a> at {g.fetched_at}.
        Each quote was checked word for word against the official text
        {g.dropped ? `; ${g.dropped} rule(s) without a matching quote were discarded` : ""}.
      </p>
      <ul className="space-y-2">
        {(data.results ?? []).map((r: any, i: number) => {
          const [label, cls] = r.passed === true ? ["PASS", "bg-emerald-100 text-emerald-800"]
            : r.passed === false ? ["FAIL", "bg-red-100 text-red-800"] : ["REVIEW", "bg-amber-100 text-amber-800"];
          return (
            <li key={i} className="rounded border border-slate-200 p-2 text-sm">
              <div className="flex items-start gap-2">
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${cls}`}>{label}</span>
                <span>{r.reason}</span>
              </div>
              <blockquote className="mt-1 border-l-2 border-slate-300 pl-2 text-xs italic text-slate-600">“{r.rule?.quote}”</blockquote>
            </li>
          );
        })}
      </ul>
      <div className="flex gap-2">
        <button onClick={() => onRespond({ proceed: true })} className={`${BTN} flex-1 bg-indigo-600 text-white`}>Proceed with application</button>
        <button onClick={() => onRespond({ proceed: false })} className={`${BTN} bg-slate-200`}>Stop</button>
      </div>
    </div>
  );
}

function HumanStep({ data, onRespond }: { data: any; onRespond: (v: any) => void }) {
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">{data.reason}</p>
      <p className="text-xs text-slate-600">
        The agent never handles OTPs, CAPTCHAs or passwords. Complete this step in the agent&apos;s browser window, then continue.
        For the test portal, the OTP is on the{" "}
        <a href="http://localhost:8001/admin" target="_blank" rel="noreferrer" className="underline">admin page</a>.
      </p>
      <button onClick={() => onRespond({ done: true })} className={`${BTN} w-full bg-indigo-600 text-white`}>
        I&apos;ve completed it — continue
      </button>
    </div>
  );
}

function MissingInfo({ data, onRespond }: { data: any; onRespond: (v: any) => void }) {
  const [key, setKey] = useState<string>(data.suggested_key ?? "");
  const [value, setValue] = useState("");
  return (
    <div className="space-y-2">
      <p className="text-sm">{data.reason}</p>
      <p className="text-xs text-slate-500">The agent will not guess. What you enter is recorded as provided by you.</p>
      <input value={key} onChange={(e) => setKey(e.target.value)} placeholder="Field"
        className="block w-full rounded border border-slate-300 px-2 py-1 text-sm" />
      <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Value"
        className="block w-full rounded border border-slate-300 px-2 py-1 text-sm" />
      <button disabled={!key.trim() || !value.trim()} onClick={() => onRespond({ key: key.trim(), value: value.trim() })}
        className={`${BTN} w-full bg-indigo-600 text-white`}>Provide value</button>
    </div>
  );
}

function Approval({ data, onRespond }: { data: any; onRespond: (v: any) => void }) {
  const sources: Record<string, string> = data.sources ?? {};
  return (
    <div className="space-y-3">
      <p className="text-sm">The agent filled the portal and stopped at its review page. <b>Nothing has been submitted.</b></p>
      {(data.unverified ?? []).length > 0 ? (
        <div className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-800">
          <b>Not from your verified profile:</b>{" "}
          {data.unverified.map(([l, v]: [string, string]) => `${l}: "${v}"`).join("; ")}.
          The portal may have reused an old draft. Decline, or approve only if these are correct.
        </div>
      ) : (
        <div className="rounded border border-emerald-300 bg-emerald-50 p-2 text-xs text-emerald-800">
          ✓ Every value on the review page matches your verified profile.
        </div>
      )}
      <table className="w-full text-sm">
        <tbody>
          {(data.rows ?? []).map(([label, value]: [string, string], i: number) => (
            <tr key={i} className="border-t border-slate-100">
              <td className="py-1 pr-2 text-xs text-slate-500">{label}</td>
              <td className="py-1 font-medium">{value || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <details className="text-xs">
        <summary className="cursor-pointer text-slate-600">Where each value came from</summary>
        <div className="mt-1 flex flex-wrap gap-1">
          {Object.entries(sources).map(([k, s]) => <span key={k}><span className="text-slate-500">{k}:</span> <SourceBadge source={s} /></span>)}
        </div>
      </details>
      <div className="flex gap-2">
        <button onClick={() => onRespond({ approved: true })} className={`${BTN} flex-1 bg-emerald-600 text-white`}>Approve &amp; submit</button>
        <button onClick={() => onRespond({ approved: false })} className={`${BTN} bg-slate-200`}>Decline</button>
      </div>
    </div>
  );
}

function PausePanel({ data, onRespond }: { data: any; onRespond: (v: any) => void }) {
  switch (data.kind) {
    case "confirm_profile": return <ConfirmProfile data={data} onRespond={onRespond} />;
    case "eligibility": return <Eligibility data={data} onRespond={onRespond} />;
    case "human_step": return <HumanStep data={data} onRespond={onRespond} />;
    case "missing_info": return <MissingInfo data={data} onRespond={onRespond} />;
    case "approval": return <Approval data={data} onRespond={onRespond} />;
    default: return <button onClick={() => onRespond(null)} className={`${BTN} bg-slate-200`}>Continue</button>;
  }
}

function ReceiptCard({ r }: { r: any }) {
  return (
    <Card title="Receipt">
      <div className="text-xs text-slate-500">Application ID</div>
      <div className="font-mono text-2xl font-bold">{r.application_id ?? "—"}</div>
      <span className={`mt-1 inline-block rounded px-2 py-0.5 text-xs font-medium ${r.verified_on_page ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
        {r.verified_on_page ? "✓ ID verified on the portal's own page" : "ID not found on page"}
      </span>
      <dl className="mt-3 grid grid-cols-3 gap-y-1 text-xs">
        <dt className="text-slate-500">Status</dt><dd className="col-span-2">{r.status}</dd>
        <dt className="text-slate-500">Captured</dt><dd className="col-span-2">{r.captured_at}</dd>
        <dt className="text-slate-500">Steps taken</dt><dd className="col-span-2">{r.steps_taken}</dd>
        <dt className="text-slate-500">Eligibility</dt><dd className="col-span-2">{r.eligibility_verdict}</dd>
        <dt className="text-slate-500">Screenshot hash</dt><dd className="col-span-2 break-all font-mono">{r.screenshot_sha256?.slice(0, 32)}…</dd>
      </dl>
      <a href={`${API}/receipts/${r.run_id}_ack.png`} target="_blank" rel="noreferrer">
        <img src={`${API}/receipts/${r.run_id}_ack.png`} alt="Acknowledgement page" className="mt-3 rounded border border-slate-200" />
      </a>
      <a href={`${API}/receipts/${r.run_id}_evidence.pdf`} target="_blank" rel="noreferrer"
        className="mt-3 block rounded bg-slate-900 px-3 py-2 text-center text-sm font-medium text-white">
        Download evidence pack (PDF)
      </a>
    </Card>
  );
}

const STAGES = ["Read documents", "Confirm details", "Eligibility", "Fill portal", "Your approval", "Submit", "Receipt"];

function stageOf(e: Ev): number {
  const m = e.message;
  if (e.type === "receipt" || (e.type === "done" && e.data?.receipt)) return 6;
  if (m.startsWith("Submitting")) return 5;
  if (e.type === "interrupt" && e.data?.kind === "approval") return 4;
  if (m.startsWith("Filling")) return 3;
  if (m.startsWith("Checking eligibility") || (e.type === "interrupt" && e.data?.kind === "eligibility")) return 2;
  if (e.type === "interrupt" && e.data?.kind === "confirm_profile") return 1;
  if (m.startsWith("Reading")) return 0;
  return -1;
}

function Stepper({ stage, done }: { stage: number; done: boolean }) {
  return (
    <ol className="flex flex-wrap items-center gap-2 px-4 pt-4">
      {STAGES.map((s, i) => {
        const state = done || i < stage ? "done" : i === stage ? "now" : "todo";
        const cls = state === "done" ? "bg-emerald-600 text-white"
          : state === "now" ? "bg-indigo-600 text-white ring-4 ring-indigo-200"
          : "border border-slate-300 bg-white text-slate-500";
        return (
          <li key={s} className="flex items-center gap-2">
            <span className={`flex h-7 items-center gap-1.5 rounded-full px-3 text-xs font-medium ${cls}`}>
              {state === "done" ? "✓" : i + 1} {s}
            </span>
            {i < STAGES.length - 1 && <span className="h-px w-4 bg-slate-300" />}
          </li>
        );
      })}
    </ol>
  );
}

function AgentView({ ev }: { ev: Ev | undefined }) {
  if (!ev) return null;
  return (
    <Card title="Agent's view">
      <img src={`${API}/screenshots/${ev.data.shot}`} alt="Latest screenshot of the agent's browser"
        className="w-full rounded border border-slate-200" />
      <p className={`mt-2 text-xs ${ev.data.ok === false ? "text-red-700" : "text-slate-600"}`}>{ev.message}</p>
    </Card>
  );
}

function fmt(sec: number) {
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

// ---------- Page ----------

export default function Home() {
  const [files, setFiles] = useState<File[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [events, setEvents] = useState<Ev[]>([]);
  const [answered, setAnswered] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recoverId, setRecoverId] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const feedEnd = useRef<HTMLDivElement | null>(null);

  useEffect(() => { feedEnd.current?.scrollIntoView({ behavior: "smooth" }); }, [events.length]);
  useEffect(() => () => wsRef.current?.close(), []);

  function connect(id: string) {
    wsRef.current?.close();
    setEvents([]);
    setAnswered(-1);
    const ws = new WebSocket(`${WS}/runs/${id}/events`);
    ws.onmessage = (m) => setEvents((prev) => [...prev, JSON.parse(m.data)]);
    ws.onerror = () => setError("Lost connection to the agent server");
    wsRef.current = ws;
  }

  async function start() {
    if (!files.length) return;
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      fd.append("scheme", "csss");
      const r = await fetch(`${API}/runs/upload`, { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      const { run_id } = await r.json();
      setRunId(run_id);
      connect(run_id);
    } catch (e: any) {
      setError(`Could not start: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function recover() {
    const id = recoverId.trim();
    if (!id) return;
    setError(null);
    const r = await fetch(`${API}/runs/${id}/recover`, { method: "POST" });
    if (!r.ok) { setError(`Recover failed: ${await r.text()}`); return; }
    setRunId(id);
    connect(id);
  }

  const lastInterrupt = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) if (events[i].type === "interrupt") return i;
    return -1;
  }, [events]);
  const pending = lastInterrupt > answered && lastInterrupt === events.length - 1 ? events[lastInterrupt].data : null;

  async function respond(value: any) {
    if (!runId) return;
    setAnswered(lastInterrupt);
    const r = await fetch(`${API}/runs/${runId}/resume`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value }),
    });
    if (!r.ok) { setError(`Could not send: ${await r.text()}`); setAnswered(-1); }
  }

  const stats = useMemo(() => ({
    actions: events.filter((e) => e.type === "act").length,
    failed: events.filter((e) => e.type === "verify" && e.data?.ok === false).length,
    recoveries: events.filter((e) => e.type === "recover").length,
    security: events.filter((e) => e.type === "security").length,
    modelPlans: events.filter((e) => e.type === "decide" && e.data?.source === "model").length,
    replays: events.filter((e) => e.type === "decide" && e.data?.source === "skill").length,
  }), [events]);
  const receipt = events.find((e) => e.type === "receipt")?.data;
  const finished = events.find((e) => e.type === "done" || e.message.startsWith("Workflow error"));
  const stage = useMemo(() => events.reduce((m, e) => Math.max(m, stageOf(e)), -1), [events]);
  const lastShot = useMemo(() => [...events].reverse().find((e) => e.type === "verify" && e.data?.shot), [events]);
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (!runId || finished) return;
    setNow(Date.now() / 1000);
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [runId, finished]);
  const t0 = events[0]?.ts;
  const elapsed = t0 ? Math.max(0, Math.round((finished ? finished.ts : now) - t0)) : 0;

  return (
    <main className="min-h-screen">
      <header className="flex items-center justify-between bg-slate-900 px-6 py-4 text-white">
        <div>
          <h1 className="text-xl font-semibold">Civic Agent</h1>
          <p className="text-sm text-slate-300">
            Autonomous public-service execution · every value traced to its source · nothing submitted without your approval
          </p>
        </div>
        {runId && (
          <div className="text-right">
            <div className="font-mono text-2xl font-semibold tabular-nums">{fmt(elapsed)}</div>
            <div className="font-mono text-xs text-slate-400">run {runId}</div>
          </div>
        )}
      </header>

      {error && <div className="mx-4 mt-4 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">{error}</div>}

      {runId && <Stepper stage={stage} done={!!receipt} />}
      <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-12">
        <section className="space-y-4 lg:col-span-3">
          <Card title="1 · Upload documents">
            <p className="mb-3 text-sm text-slate-600">Your real marksheets, certificates or declarations (PDF or photo).</p>
            <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              className="block w-full text-sm file:mr-3 file:rounded file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-white" />
            {files.length > 0 && <ul className="mt-2 text-xs text-slate-600">{files.map((f) => <li key={f.name}>• {f.name}</li>)}</ul>}
            <p className="mt-3 text-xs text-slate-500">
              Scheme: Central Sector Scheme of Scholarship — eligibility read live from myScheme.
            </p>
            <button onClick={start} disabled={!files.length || busy} className={`${BTN} mt-3 w-full bg-indigo-600 text-white`}>
              {busy ? "Starting…" : "Start agent"}
            </button>
          </Card>

          <Card title="Live counters">
            <div className="grid grid-cols-2 gap-2 text-center">
              {[["Actions", stats.actions, "text-slate-900"], ["Failed checks", stats.failed, "text-red-600"],
                ["Recoveries", stats.recoveries, "text-amber-600"], ["Security events", stats.security, "text-rose-600"],
                ["Model plans", stats.modelPlans, "text-sky-600"], ["Learned replays", stats.replays, "text-emerald-600"]]
                .map(([label, n, cls]) => (
                  <div key={label as string} className="rounded bg-slate-50 p-2">
                    <div className={`text-2xl font-bold ${cls}`}>{n as number}</div>
                    <div className="text-[11px] text-slate-500">{label as string}</div>
                  </div>
                ))}
            </div>
          </Card>

          <Card title="Recover after a crash">
            <p className="mb-2 text-xs text-slate-600">Restart the server, then continue a run from its last checkpoint.</p>
            <div className="flex gap-2">
              <input value={recoverId} onChange={(e) => setRecoverId(e.target.value)} placeholder="run id"
                className="flex-1 rounded border border-slate-300 px-2 py-1 font-mono text-sm" />
              <button onClick={recover} className={`${BTN} bg-slate-200`}>Recover</button>
            </div>
          </Card>
        </section>

        <section className="lg:col-span-5">
          <Card title="Agent activity">
            <div className="h-[calc(100vh-190px)] space-y-1.5 overflow-y-auto pr-1">
              {events.length === 0 && (
                <p className="text-sm text-slate-500">Start a run to watch the agent observe, plan, act and verify in real time.</p>
              )}
              {events.map((e, i) => <EventRow key={i} ev={e} t0={events[0]?.ts} />)}
              <div ref={feedEnd} />
            </div>
          </Card>
        </section>

        <section className="space-y-4 lg:col-span-4">
          {pending && (
            <Card title="Action required" highlight>
              <PausePanel key={lastInterrupt} data={pending} onRespond={respond} />
            </Card>
          )}
          {!pending && runId && !finished && (
            <Card title="Status"><p className="animate-pulse text-sm text-slate-600">Agent is working…</p></Card>
          )}
          {!receipt && <AgentView ev={lastShot} />}
          {receipt && <ReceiptCard r={receipt} />}
          {finished && !receipt && <Card title="Finished"><p className="text-sm">{finished.message}</p></Card>}
        </section>
      </div>
      <footer className="pb-6 pt-2 text-center text-sm text-slate-500">
        Made with ❤️ by Ashu &amp; Aviral
      </footer>
    </main>
  );
}
