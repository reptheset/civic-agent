"use client";
/* eslint-disable @typescript-eslint/no-explicit-any, @next/next/no-img-element */
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { FIELDS, LANG_NAMES, STAGES, STR, type Lang } from "./i18n";

// Locally the API is on localhost:8000; when deployed, NEXT_PUBLIC_API points at the hosted API.
const API = (process.env.NEXT_PUBLIC_API || "http://localhost:8000").replace(/\/$/, "");
const WS = API.replace(/^http/, "ws");
const LOCAL = API.includes("localhost") || API.includes("127.0.0.1");
const RunCtx = createContext<string | null>(null);

type Ev = { type: string; message: string; data: any; ts: number };

const LangCtx = createContext<Lang>("en");
function useT() {
  const lang = useContext(LangCtx);
  const t = (k: string) => STR[lang][k] ?? STR.en[k] ?? k;
  const fl = (k: string) => FIELDS[lang][k] ?? FIELDS.en[k] ?? k;
  return { lang, t, fl };
}

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
    <div className={`rounded-lg border bg-white p-4 shadow-sm ${highlight ? "border-violet-400 ring-2 ring-violet-200" : "border-slate-200"}`}>
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
        <span className="w-20 shrink-0 pt-0.5 font-mono text-[10px] uppercase tracking-wide opacity-70">
          {ev.type}
          {t0 !== undefined && <span className="block normal-case">+{Math.round(ev.ts - t0)}s</span>}
        </span>
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
  const { t, fl } = useT();
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
        <h3 className="mb-1 text-sm font-semibold">{t("from_docs")}</h3>
        <table className="w-full text-sm">
          <tbody>
            {fields.filter((f) => !check.includes(f.key)).map((f) => (
              <tr key={f.key} className="border-t border-slate-100">
                <td className="py-1 pr-2 text-xs text-slate-500">{fl(f.key)}</td>
                <td className="py-1 pr-2 font-medium">{f.value}</td>
                <td className="py-1 text-right"><SourceBadge source={f.source} confidence={f.confidence} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {check.length > 0 && (
        <div className="rounded border border-amber-300 bg-amber-50 p-3">
          <h3 className="text-sm font-semibold text-amber-900">{t("check_these")} ({check.length})</h3>
          <p className="mb-2 text-xs text-amber-800">{t("check_desc")}</p>
          {check.map((k) => {
            const f = fields.find((x) => x.key === k);
            const mm = mismatches.find((m) => m.field === k);
            return (
              <div key={k} className="mb-3">
                <div className="text-xs font-semibold">{fl(k)}</div>
                {mm ? (
                  <div className="text-xs text-amber-900">
                    {t("docs_disagree")}{" "}
                    {Object.entries(mm.values as Record<string, string>).map(([d, v]) => `${d}: "${v}"`).join("  vs  ")}
                  </div>
                ) : (
                  <div className="text-xs">
                    {t("extracted")} <b>{f?.value}</b> <span className="opacity-70">({f?.source}, {f?.confidence})</span>
                  </div>
                )}
                <div className="mt-1 flex items-center gap-2">
                  <input disabled={!!accepted[k]} placeholder={t("type_correct")} value={vals[k] ?? ""}
                    onChange={(e) => setVals({ ...vals, [k]: e.target.value })}
                    className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-100" />
                  {!mm && (
                    <label className="flex items-center gap-1 text-xs">
                      <input type="checkbox" checked={!!accepted[k]}
                        onChange={(e) => setAccepted({ ...accepted, [k]: e.target.checked })} />
                      {t("extracted_ok")}
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
          <h3 className="mb-1 text-sm font-semibold">{t("not_on_docs")}</h3>
          {missing.map((m) => (
            <div key={m.key} className="mb-2">
              <label className="text-xs font-medium text-slate-600">{fl(m.key)}</label>
              {m.options ? (
                <select value={vals[m.key] ?? ""} onChange={(e) => setVals({ ...vals, [m.key]: e.target.value })}
                  className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-sm">
                  <option value="">{t("select")}</option>
                  {m.options.map((o: string) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input value={vals[m.key] ?? ""} onChange={(e) => setVals({ ...vals, [m.key]: e.target.value })}
                  className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-sm" />
              )}
            </div>
          ))}
          <p className="text-xs text-slate-500">{t("skip_note")}</p>
        </div>
      )}

      <button disabled={!ready} onClick={submit} className={`${BTN} w-full bg-indigo-600 text-white`}>{t("confirm_btn")}</button>
    </div>
  );
}

function Eligibility({ data, onRespond }: { data: any; onRespond: (v: any) => void }) {
  const { lang, t, fl } = useT();
  const g = data.guideline ?? {};
  const results: any[] = data.results ?? [];
  const askable: string[] = data.askable ?? [];
  const [vals, setVals] = useState<Record<string, string>>({});
  const [expl, setExpl] = useState<any>(null);
  const [state, setState] = useState<"idle" | "loading" | "failed">("idle");
  const verdictStyle: Record<string, string> = {
    eligible: "bg-emerald-600", not_eligible: "bg-red-600", needs_review: "bg-amber-500",
  };

  useEffect(() => {
    let cancelled = false;
    if (lang === "en") { setExpl(null); setState("idle"); return; }
    setState("loading");
    fetch(`${API}/explain`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: lang, verdict: data.verdict, results }),
    }).then(async (r) => {
      if (cancelled) return;
      if (r.ok) { setExpl(await r.json()); setState("idle"); } else setState("failed");
    }).catch(() => { if (!cancelled) setState("failed"); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-semibold uppercase text-white ${verdictStyle[data.verdict] ?? "bg-slate-500"}`}>
          {t(`verdict_${data.verdict}`)}
        </span>
        <span className="text-sm font-medium">{g.name}</span>
      </div>
      {state === "loading" && <p className="animate-pulse text-xs text-slate-500">{t("explaining")}</p>}
      {state === "failed" && <p className="text-xs text-amber-700">{t("expl_failed")}</p>}
      {expl?.summary && (
        <div className="rounded border border-indigo-200 bg-indigo-50 p-2 text-sm text-indigo-900">
          {expl.summary}
          <div className="mt-1 text-[10px] text-indigo-700">{t("ai_expl")}</div>
        </div>
      )}
      <p className="text-xs text-slate-500">
        {t("rules_from")} <a href={g.url} target="_blank" rel="noreferrer" className="underline">{g.url}</a> · {g.fetched_at}
        {g.sha256 && <> · SHA-256 <span className="font-mono">{g.sha256.slice(0, 12)}…</span></>}.{" "}
        {t("fresh_note")} {t("quote_checked")}
      </p>
      <ul className="space-y-2">
        {results.map((r: any, i: number) => {
          const [label, cls] = r.passed === true ? [t("pass"), "bg-emerald-100 text-emerald-800"]
            : r.passed === false ? [t("fail"), "bg-red-100 text-red-800"] : [t("review"), "bg-amber-100 text-amber-800"];
          const local = expl?.rules?.[i];
          return (
            <li key={i} className="rounded border border-slate-200 p-2 text-sm">
              <div className="flex items-start gap-2">
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${cls}`}>{label}</span>
                <span>{local ?? r.reason}</span>
              </div>
              {local && <div className="ml-12 text-[11px] text-slate-500">{r.reason}</div>}
              <blockquote className="mt-1 border-l-2 border-slate-300 pl-2 text-xs italic text-slate-600">“{r.rule?.quote}”</blockquote>
            </li>
          );
        })}
      </ul>
      {askable.length > 0 && (
        <div className="rounded border border-slate-200 p-2">
          <div className="text-sm font-semibold">{t("missing_value_title")}</div>
          <p className="mb-2 text-xs text-slate-500">{t("missing_value_note")}</p>
          {askable.map((k) => (
            <div key={k} className="mb-2">
              <label className="text-xs font-medium text-slate-600">{fl(k)}</label>
              <input value={vals[k] ?? ""} onChange={(e) => setVals({ ...vals, [k]: e.target.value })}
                className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-sm" />
            </div>
          ))}
          <button disabled={!Object.values(vals).some((v) => v.trim())} onClick={() => onRespond({ values: vals })}
            className={`${BTN} w-full bg-slate-900 text-white`}>{t("reevaluate")}</button>
        </div>
      )}
      <div className="flex gap-2">
        <button onClick={() => onRespond({ proceed: true })} className={`${BTN} flex-1 bg-indigo-600 text-white`}>{t("proceed")}</button>
        <button onClick={() => onRespond({ proceed: false })} className={`${BTN} bg-slate-200`}>{t("stop")}</button>
      </div>
    </div>
  );
}

function HumanStep({ data, onRespond }: { data: any; onRespond: (v: any) => void }) {
  const { t } = useT();
  const runId = useContext(RunCtx);
  const [code, setCode] = useState("");
  const [sms, setSms] = useState<any[]>([]);
  useEffect(() => {
    if (!runId) return;
    let alive = true;
    const load = () => fetch(`${API}/runs/${runId}/sms`).then((r) => r.json())
      .then((j) => { if (alive) setSms(j.messages ?? []); }).catch(() => {});
    load();
    const timer = setInterval(load, 2000);
    return () => { alive = false; clearInterval(timer); };
  }, [runId]);
  return (
    <div className="space-y-3">
      <p className="text-sm font-semibold">{t("human_title")}</p>
      <p className="text-xs text-slate-500">{data.reason}</p>
      <p className="text-xs text-slate-600">{t("human_desc_ui")}</p>
      <div className="rounded border border-slate-200 bg-slate-50 p-2">
        <div className="text-[11px] font-semibold uppercase text-slate-500">{t("sms_title")}</div>
        <div className="mb-1 text-[10px] text-slate-400">{t("sms_note")}</div>
        {sms.length === 0 && <div className="text-xs text-slate-500">{t("sms_empty")}</div>}
        {sms.slice(0, 1).map((m, i) => <div key={i} className="text-sm">{m.message}</div>)}
      </div>
      <input value={code} onChange={(e) => setCode(e.target.value)} placeholder={t("otp_label")} inputMode="numeric"
        className="block w-full rounded border border-slate-300 px-2 py-1.5 font-mono text-sm" />
      <button disabled={!code.trim()} onClick={() => onRespond({ __otp: code.trim() })}
        className={`${BTN} w-full bg-indigo-600 text-white`}>{t("otp_send")}</button>
      {LOCAL && (
        <button onClick={() => onRespond({ done: true })} className={`${BTN} w-full border border-slate-300 bg-white text-slate-900`}>
          {t("completed")}
        </button>
      )}
    </div>
  );
}

function PortalFaults() {
  const { t } = useT();
  const [faults, setFaults] = useState<any[]>([]);
  useEffect(() => {
    fetch(`${API}/portal/faults`).then((r) => r.json()).then((j) => setFaults(j.faults ?? [])).catch(() => {});
  }, []);
  async function toggle(name: string) {
    const r = await fetch(`${API}/portal/faults/${name}`, { method: "POST" });
    if (r.ok) setFaults((await r.json()).faults ?? []);
  }
  return (
    <Card title={t("faults_title")}>
      <p className="mb-2 text-xs text-slate-600">{t("faults_note")}</p>
      <div className="space-y-1.5">
        {faults.map((f) => (
          <label key={f.name} className="flex cursor-pointer items-start gap-2 text-xs">
            <input type="checkbox" checked={f.on} onChange={() => toggle(f.name)} className="mt-0.5" />
            <span><span className="font-mono font-semibold">{f.name}</span> <span className="text-slate-500">{f.desc}</span></span>
          </label>
        ))}
      </div>
    </Card>
  );
}

function MissingInfo({ data, onRespond }: { data: any; onRespond: (v: any) => void }) {
  const { t, fl } = useT();
  const [key, setKey] = useState<string>(data.suggested_key ?? "");
  const [value, setValue] = useState("");
  return (
    <div className="space-y-2">
      <p className="text-sm font-semibold">{t("missing_title")}{key ? `: ${fl(key)}` : ""}</p>
      <p className="text-xs text-slate-500">{data.reason}</p>
      <p className="text-xs text-slate-600">{t("missing_desc")}</p>
      <input value={key} onChange={(e) => setKey(e.target.value)} placeholder={t("field")}
        className="block w-full rounded border border-slate-300 px-2 py-1 text-sm" />
      <input value={value} onChange={(e) => setValue(e.target.value)} placeholder={t("value")}
        className="block w-full rounded border border-slate-300 px-2 py-1 text-sm" />
      <button disabled={!key.trim() || !value.trim()} onClick={() => onRespond({ key: key.trim(), value: value.trim() })}
        className={`${BTN} w-full bg-indigo-600 text-white`}>{t("provide")}</button>
    </div>
  );
}

function Approval({ data, onRespond }: { data: any; onRespond: (v: any) => void }) {
  const { t, fl } = useT();
  const sources: Record<string, string> = data.sources ?? {};
  const bad: [string, string][] = data.unverified ?? [];
  return (
    <div className="space-y-3">
      <p className="text-sm">{t("approval_intro")} <b>{t("nothing_submitted")}</b></p>
      {bad.length > 0 ? (
        <div className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-800">
          <b>{t("unverified_title")}</b> {bad.map(([l, v]) => `${l}: "${v}"`).join("; ")}. {t("unverified_note")}
        </div>
      ) : (
        <div className="rounded border border-emerald-300 bg-emerald-50 p-2 text-xs text-emerald-800">{t("all_match")}</div>
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
        <summary className="cursor-pointer text-slate-600">{t("where_from")}</summary>
        <div className="mt-1 flex flex-wrap gap-1">
          {Object.entries(sources).map(([k, s]) => <span key={k}><span className="text-slate-500">{fl(k)}:</span> <SourceBadge source={s} /></span>)}
        </div>
      </details>
      <div className="flex gap-2">
        <button onClick={() => onRespond({ approved: true })} className={`${BTN} flex-1 bg-emerald-600 text-white`}>{t("approve")}</button>
        <button onClick={() => onRespond({ approved: false })} className={`${BTN} bg-slate-200`}>{t("decline")}</button>
      </div>
    </div>
  );
}

function PausePanel({ data, onRespond }: { data: any; onRespond: (v: any) => void }) {
  const { t } = useT();
  switch (data.kind) {
    case "confirm_profile": return <ConfirmProfile data={data} onRespond={onRespond} />;
    case "eligibility": return <Eligibility data={data} onRespond={onRespond} />;
    case "human_step": return <HumanStep data={data} onRespond={onRespond} />;
    case "missing_info": return <MissingInfo data={data} onRespond={onRespond} />;
    case "approval": return <Approval data={data} onRespond={onRespond} />;
    default: return <button onClick={() => onRespond(null)} className={`${BTN} bg-slate-200`}>{t("continue")}</button>;
  }
}

function ReceiptCard({ r, track, onTrack, tracking }: { r: any; track?: any; onTrack: () => void; tracking: boolean }) {
  const { t } = useT();
  return (
    <Card title={t("receipt")}>
      <div className="text-xs text-slate-500">{t("app_id")}</div>
      <div className="font-mono text-2xl font-bold">{r.application_id ?? "—"}</div>
      <span className={`mt-1 inline-block rounded px-2 py-0.5 text-xs font-medium ${r.verified_on_page ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
        {r.verified_on_page ? t("verified_id") : t("id_missing")}
      </span>
      <dl className="mt-3 grid grid-cols-3 gap-y-1 text-xs">
        <dt className="text-slate-500">{t("status")}</dt><dd className="col-span-2">{r.status}</dd>
        <dt className="text-slate-500">{t("captured")}</dt><dd className="col-span-2">{r.captured_at}</dd>
        <dt className="text-slate-500">{t("steps")}</dt><dd className="col-span-2">{r.steps_taken}</dd>
        <dt className="text-slate-500">{t("eligibility_l")}</dt><dd className="col-span-2">{r.eligibility_verdict}</dd>
        {r.reliability && <>
          <dt className="text-slate-500">{t("verified_actions")}</dt>
          <dd className="col-span-2">{r.reliability.verified_actions}/{r.reliability.actions} ({r.reliability.verification_rate}%) · {t("fields_l")} {r.reliability.fields_verified}/{r.reliability.field_checks}</dd>
          <dt className="text-slate-500">{t("plans_replays")}</dt>
          <dd className="col-span-2">{r.reliability.model_plans} / {r.reliability.learned_replays}</dd>
          <dt className="text-slate-500">{t("submit_clicks")}</dt>
          <dd className="col-span-2">{r.reliability.final_submit_clicks} {t("submit_clicks_note")}</dd>
        </>}
        <dt className="text-slate-500">{t("hash")}</dt><dd className="col-span-2 break-all font-mono">{r.screenshot_sha256?.slice(0, 32)}…</dd>
      </dl>
      <a href={`${API}/receipts/${r.run_id}_ack.png`} target="_blank" rel="noreferrer">
        <img src={`${API}/receipts/${r.run_id}_ack.png`} alt="Acknowledgement page" className="mt-3 rounded border border-slate-200" />
      </a>
      <a href={`${API}/receipts/${r.run_id}_evidence.pdf`} target="_blank" rel="noreferrer"
        className="mt-3 block rounded bg-slate-900 px-3 py-2 text-center text-sm font-medium text-white">
        {t("download")}
      </a>
      <button onClick={onTrack} disabled={tracking}
        className={`${BTN} mt-2 w-full border border-slate-300 bg-white text-slate-900`}>
        {tracking ? t("tracking") : t("track_btn")}
      </button>
      {track && (
        <div className="mt-2 rounded border border-emerald-200 bg-emerald-50 p-2 text-xs">
          <div className="text-slate-500">{t("latest_status")}</div>
          <div className="text-sm font-semibold">{track.status ?? "—"}</div>
          <div className={track.verified_on_page ? "text-emerald-700" : "text-red-700"}>
            {track.verified_on_page ? t("status_verified") : t("id_missing")}
          </div>
          <div className="text-slate-500">{t("checked_at")}: {track.checked_at}</div>
          <a href={`${API}/screenshots/${track.shot}`} target="_blank" rel="noreferrer" className="underline">screenshot</a>
        </div>
      )}
    </Card>
  );
}

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
  const { lang } = useT();
  const stages = STAGES[lang];
  return (
    <ol className="flex flex-wrap items-center gap-2 px-4 pt-4">
      {stages.map((s, i) => {
        const state = done || i < stage ? "done" : i === stage ? "now" : "todo";
        const cls = state === "done" ? "bg-emerald-600 text-white"
          : state === "now" ? "bg-indigo-600 text-white ring-4 ring-indigo-200"
          : "border border-slate-300 bg-white text-slate-500";
        return (
          <li key={i} className="flex items-center gap-2">
            <span className={`flex h-7 items-center gap-1.5 rounded-full px-3 text-xs font-medium ${cls}`}>
              {state === "done" ? "✓" : i + 1} {s}
            </span>
            {i < stages.length - 1 && <span className="h-px w-4 bg-slate-300" />}
          </li>
        );
      })}
    </ol>
  );
}

function AgentView({ ev, prompt }: { ev: Ev | undefined; prompt?: string }) {
  const { t } = useT();
  if (!ev) return null;
  return (
    <Card title={t("agent_view")}>
      <img src={`${API}/screenshots/${ev.data.shot}`} alt="Latest screenshot of the agent's browser"
        className="w-full rounded border border-slate-200" />
      <p className={`mt-2 text-xs ${ev.data.ok === false ? "text-red-700" : "text-slate-600"}`}>{ev.message}</p>
      {prompt && (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer font-medium text-slate-700">{t("ai_saw")}</summary>
          <p className="mt-1 text-slate-500">{t("ai_saw_note")}</p>
          <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded bg-slate-900 p-2 text-[10px] text-slate-100">{prompt}</pre>
        </details>
      )}
    </Card>
  );
}

function fmt(sec: number) {
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

// ---------- Page ----------

export default function Home() {
  const [lang, setLang] = useState<Lang>("en");
  const [files, setFiles] = useState<File[]>([]);
  const [schemeUrl, setSchemeUrl] = useState("");
  const [docsInfo, setDocsInfo] = useState<any>(null);
  const [docsBusy, setDocsBusy] = useState(false);

  async function checkDocs() {
    setDocsBusy(true);
    setError(null);
    setDocsInfo(null);
    try {
      const r = await fetch(`${API}/scheme/documents`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scheme_url: schemeUrl.trim() }),
      });
      if (!r.ok) throw new Error(await r.text());
      setDocsInfo(await r.json());
    } catch (e: any) {
      setError(`Could not read the documents list: ${e.message}`);
    } finally {
      setDocsBusy(false);
    }
  }
  const [runId, setRunId] = useState<string | null>(null);
  const [events, setEvents] = useState<Ev[]>([]);
  const [answered, setAnswered] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recoverId, setRecoverId] = useState("");
  const [tracking, setTracking] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const feedBox = useRef<HTMLDivElement | null>(null);
  const stickToBottom = useRef(true);   // follow new events only while the reader is at the bottom of the feed
  const t = (k: string) => STR[lang][k] ?? STR.en[k] ?? k;

  // Scroll ONLY the activity feed (never the page), and only if the reader has not scrolled up in it.
  useEffect(() => {
    const el = feedBox.current;
    if (el && stickToBottom.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [events.length]);
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
      if (schemeUrl.trim()) fd.append("scheme_url", schemeUrl.trim());
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

  async function trackStatus() {
    if (!runId) return;
    setTracking(true);
    setError(null);
    try {
      const r = await fetch(`${API}/runs/${runId}/track`, { method: "POST" });
      if (!r.ok) setError(`Tracking failed: ${await r.text()}`);
    } finally {
      setTracking(false);
    }
  }

  const lastInterrupt = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) if (events[i].type === "interrupt") return i;
    return -1;
  }, [events]);
  const pending = lastInterrupt > answered && lastInterrupt === events.length - 1 ? events[lastInterrupt].data : null;

  async function respond(value: any) {
    if (!runId) return;
    setAnswered(lastInterrupt);
    const otp = value && typeof value === "object" && "__otp" in value;
    const r = await fetch(`${API}/runs/${runId}/${otp ? "human-input" : "resume"}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(otp ? { value: value.__otp } : { value }),
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
  const track = useMemo(() => [...events].reverse().find((e) => e.type === "track")?.data, [events]);
  const finished = events.find((e) => e.type === "done" || e.message.startsWith("Workflow error"));
  const stage = useMemo(() => events.reduce((m, e) => Math.max(m, stageOf(e)), -1), [events]);
  const lastShot = useMemo(() => [...events].reverse().find((e) => e.type === "verify" && e.data?.shot), [events]);
  const lastPrompt = useMemo(() => [...events].reverse().find((e) => e.type === "decide" && e.data?.prompt)?.data.prompt, [events]);
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (!runId || finished) return;
    setNow(Date.now() / 1000);
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [runId, finished]);
  const t0 = events[0]?.ts;
  const elapsed = t0 ? Math.max(0, Math.round((finished ? finished.ts : now) - t0)) : 0;

  const counters: [string, number, string][] = [
    ["actions", stats.actions, "text-slate-900"], ["failed", stats.failed, "text-red-600"],
    ["recoveries", stats.recoveries, "text-amber-600"], ["security", stats.security, "text-rose-600"],
    ["model_plans", stats.modelPlans, "text-sky-600"], ["replays", stats.replays, "text-emerald-600"],
  ];

  return (
    <LangCtx.Provider value={lang}>
    <RunCtx.Provider value={runId}>
      <main className="min-h-screen">
        <header className="flex flex-wrap items-center justify-between gap-3 bg-slate-900 px-6 py-4 text-white">
          <div>
            <h1 className="text-xl font-semibold">Civic Agent</h1>
            <p className="text-sm text-slate-300">{t("tagline")}</p>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1">
              <span className="mr-1 text-xs text-slate-400">{t("language")}</span>
              {LANG_NAMES.map(([k, label]) => (
                <button key={k} onClick={() => setLang(k)}
                  className={`rounded px-2.5 py-1 text-xs font-medium ${lang === k ? "bg-white text-slate-900" : "bg-slate-800 text-slate-200"}`}>
                  {label}
                </button>
              ))}
            </div>
            {runId && (
              <div className="text-right">
                <div className="font-mono text-2xl font-semibold tabular-nums">{fmt(elapsed)}</div>
                <div className="font-mono text-xs text-slate-400">run {runId}</div>
              </div>
            )}
          </div>
        </header>

        {error && <div className="mx-4 mt-4 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">{error}</div>}

        {runId && <Stepper stage={stage} done={!!receipt} />}
        <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-12">
          <section className="space-y-4 lg:col-span-3">
            <Card title={t("upload_title")}>
              <p className="mb-3 text-sm text-slate-600">{t("upload_desc")}</p>
              <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png"
                onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                className="block w-full text-sm file:mr-3 file:rounded file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-white" />
              {files.length > 0 && <ul className="mt-2 text-xs text-slate-600">{files.map((f) => <li key={f.name}>• {f.name}</li>)}</ul>}
              <p className="mt-3 text-xs text-slate-500">{t("scheme_note")}</p>
              <label className="mt-2 block text-xs font-medium text-slate-600">{t("scheme_url_label")}</label>
              <input value={schemeUrl} onChange={(e) => setSchemeUrl(e.target.value)} type="url"
                placeholder="https://www.myscheme.gov.in/schemes/..."
                className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-xs" />
              <p className="mt-1 text-[10px] text-slate-400">{t("scheme_url_note")}</p>
              <button onClick={checkDocs} disabled={docsBusy}
                className={`${BTN} mt-2 w-full border border-slate-300 bg-white text-slate-900`}>
                {docsBusy ? t("docs_busy") : t("docs_btn")}
              </button>
              {docsInfo && (
                <div className="mt-2 rounded border border-emerald-200 bg-emerald-50 p-2 text-xs text-slate-800">
                  <div className="font-semibold">{t("docs_title")}</div>
                  {docsInfo.documents.length === 0 && <div className="text-slate-600">{t("docs_none")}</div>}
                  <ul className="mt-1 space-y-1">
                    {docsInfo.documents.map((d: any, i: number) => (
                      <li key={i}><span className="font-medium">• {d.name}</span>
                        <div className="pl-3 text-[10px] italic text-slate-500">“{d.quote}”</div></li>
                    ))}
                  </ul>
                  <div className="mt-1 text-[10px] text-slate-500">
                    {t("rules_from")} {docsInfo.url} · {docsInfo.fetched_at} · SHA-256 {String(docsInfo.sha256).slice(0, 12)}… {t("quote_checked")}
                  </div>
                </div>
              )}
              <button onClick={start} disabled={!files.length || busy} className={`${BTN} mt-3 w-full bg-indigo-600 text-white`}>
                {busy ? t("starting") : t("start")}
              </button>
            </Card>

            <Card title={t("counters")}>
              <div className="grid grid-cols-2 gap-2 text-center">
                {counters.map(([key, n, cls]) => (
                  <div key={key} className="rounded bg-slate-50 p-2">
                    <div className={`text-2xl font-bold ${cls}`}>{n}</div>
                    <div className="text-[11px] text-slate-500">{t(key)}</div>
                  </div>
                ))}
              </div>
            </Card>

            <PortalFaults />

            <Card title={t("recover_title")}>
              <p className="mb-2 text-xs text-slate-600">{t("recover_desc")}</p>
              <div className="flex gap-2">
                <input value={recoverId} onChange={(e) => setRecoverId(e.target.value)} placeholder="run id"
                  className="flex-1 rounded border border-slate-300 px-2 py-1 font-mono text-sm" />
                <button onClick={recover} className={`${BTN} bg-slate-200`}>{t("recover_btn")}</button>
              </div>
            </Card>
          </section>

          <section className="lg:col-span-5">
            <Card title={t("activity")}>
              {t("activity_note") && <p className="-mt-2 mb-2 text-xs text-slate-400">{t("activity_note")}</p>}
              <div ref={feedBox} onScroll={(e) => {
                  const el = e.currentTarget;
                  stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
                }} className="h-[calc(100vh-190px)] space-y-1.5 overflow-y-auto pr-1">
                {events.length === 0 && <p className="text-sm text-slate-500">{t("activity_empty")}</p>}
                {events.map((e, i) => <EventRow key={i} ev={e} t0={events[0]?.ts} />)}
              </div>
            </Card>
          </section>

          <section className="space-y-4 lg:col-span-4">
            {pending && (
              <Card title={t("action_required")} highlight>
                <PausePanel key={lastInterrupt} data={pending} onRespond={respond} />
              </Card>
            )}
            {!pending && runId && !finished && (
              <Card title={t("status")}><p className="animate-pulse text-sm text-slate-600">{t("working")}</p></Card>
            )}
            {!receipt && <AgentView ev={lastShot} prompt={lastPrompt} />}
            {receipt && <ReceiptCard r={receipt} track={track} onTrack={trackStatus} tracking={tracking} />}
            {finished && !receipt && <Card title={t("finished")}><p className="text-sm">{finished.message}</p></Card>}
          </section>
        </div>
      </main>
    </RunCtx.Provider>
    </LangCtx.Provider>
  );
}
