import {
  ArrowSquareOut,
  CaretRight,
  ChatTeardropText,
  Check,
  CheckCircle,
  CircleNotch,
  Code,
  Compass,
  Copy,
  DotOutline,
  SealCheck,
  ShieldCheck,
  Table,
  ThumbsDown,
  ThumbsUp,
  Timer,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useId, useState, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Arm, Config } from "../api";
import type { Rating, Step } from "../chatApi";
import { routeLabel, tableName } from "../format";
import { useChat, type Reply } from "./state";

export const ARM_NAME: Record<Arm, string> = {
  genie_one: "Genie One fallback",
  custom_agent: "Custom agent fallback",
};

const REASONS = ["Wrong number", "Wrong agent or table", "Used data outside the scope", "Too slow", "Hard to follow"];

export function ArmIcon({ arm, size = 14 }: { arm: Arm; size?: number }) {
  return arm === "genie_one" ? <Compass size={size} weight="bold" /> : <ShieldCheck size={size} weight="bold" />;
}

function RouteIcon({ route }: { route: string }) {
  if (route === "genie_one") return <Compass size={14} weight="bold" />;
  if (route === "fallback_agent") return <ShieldCheck size={14} weight="bold" />;
  return <SealCheck size={14} weight="bold" />;
}

function useElapsed(startedAt: number, running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [running]);
  return Math.max(0, (now - startedAt) / 1000);
}

function stepTitle(step: Step): string {
  if (step.kind === "call" && step.route?.startsWith("genie:")) {
    return step.status === "running" ? `Asking ${routeLabel(step.route)}` : `Asked ${routeLabel(step.route)}`;
  }
  return step.title;
}

function StepRow({ step }: { step: Step }) {
  const icon =
    step.status === "failed" ? (
      <WarningCircle size={16} weight="fill" />
    ) : step.kind === "note" ? (
      <ChatTeardropText size={16} />
    ) : step.kind === "progress" ? (
      <DotOutline size={16} weight="fill" />
    ) : step.status === "running" ? (
      <CircleNotch size={16} weight="bold" className="spin" />
    ) : (
      <CheckCircle size={16} weight="fill" />
    );
  return (
    <li className="step" data-kind={step.kind} data-status={step.status}>
      <span className="step-icon" aria-hidden="true">
        {icon}
      </span>
      <div>
        <div className="step-title">{step.kind === "progress" ? <ProgressText text={step.title} /> : stepTitle(step)}</div>
        {step.kind === "call" && step.detail && <div className="step-detail">{step.detail}</div>}
      </div>
      <span className="step-time">
        {step.duration_s !== null && step.kind === "call" ? `${step.duration_s.toFixed(1)} s` : ""}
      </span>
    </li>
  );
}

/** The custom agent's own steps are tool names, so they read better as code. */
function ProgressText({ text }: { text: string }) {
  const tool = /^(list_tables|read_table|search_tables|run_sql)\b(.*)$/.exec(text);
  if (!tool) return <>{text}</>;
  return (
    <>
      <code>{tool[1]}</code>
      {tool[2]}
    </>
  );
}

function Thinking({ reply }: { reply: Reply }) {
  const running = reply.status === "streaming";
  const [open, setOpen] = useState(running);
  const [touched, setTouched] = useState(false);
  const elapsed = useElapsed(reply.startedAt, running);
  const listId = useId();

  useEffect(() => {
    if (!touched) setOpen(running);
  }, [running, touched]);

  // The text being written sits in the answer area until a tool call shows it was only a note.
  const draft = reply.draft.trim();
  const steps = reply.steps.filter(
    (step, index) =>
      !(step.kind === "note" && index === reply.steps.length - 1 && draft && draft.startsWith(step.title.replace(/…$/, ""))),
  );
  const current = [...steps].reverse().find((step) => step.status === "running");
  const seconds = running ? elapsed : (reply.final?.latency_s ?? 0);
  const calls = steps.filter((step) => step.kind !== "note").length;

  if (!running && steps.length === 0) return null;
  const label = running
    ? current
      ? stepTitle(current)
      : draft
        ? "Writing"
        : steps.length
          ? "Reading the result"
          : "Choosing an agent"
    : `Worked for ${seconds.toFixed(0)} s`;

  return (
    <div className="thinking" data-open={open}>
      <button
        type="button"
        className="thinking-head"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => {
          setTouched(true);
          setOpen(!open);
        }}
      >
        {running ? <span className="live-dot" aria-hidden="true" /> : <Timer size={16} aria-hidden="true" />}
        <span className={running ? "now" : undefined}>{label}</span>
        {running ? (
          <span className="timer">{elapsed.toFixed(0)} s</span>
        ) : (
          <span>
            in {calls} {calls === 1 ? "step" : "steps"}
          </span>
        )}
        <CaretRight size={14} className="caret" aria-hidden="true" />
      </button>
      {open && (
        <ol className="steps-list" id={listId} aria-live={running ? "polite" : undefined}>
          {steps.length === 0 && (
            <li className="step" data-kind="progress">
              <span className="step-icon" aria-hidden="true">
                <DotOutline size={16} weight="fill" />
              </span>
              <div className="step-title">The supervisor is reading the question and choosing an agent.</div>
              <span />
            </li>
          )}
          {steps.map((step) => (
            <StepRow key={step.id} step={step} />
          ))}
        </ol>
      )}
    </div>
  );
}

export function Markdown({ text, writing = false }: { text: string; writing?: boolean }) {
  return (
    <div className={writing ? "answer writing" : "answer"}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: (props) => <a {...props} target="_blank" rel="noreferrer" /> }}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

function CopyButton({ text, label, className = "icon-button" }: { text: string; label: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={className}
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1400);
        });
      }}
    >
      {copied ? <Check size={16} weight="bold" /> : <Copy size={16} />}
    </button>
  );
}

function Used({ reply, config }: { reply: Reply; config: Config }) {
  const final = reply.final!;
  const [panel, setPanel] = useState<"sql" | "tables" | null>(null);
  const arm = config.arms.find((a) => a.key === reply.arm);
  const genieLink = reply.steps.find((step) => step.link)?.link;
  const traceUrl =
    final.trace_id && arm?.experiment_id && config.workspace_host && !config.fixtures
      ? `${config.workspace_host}/ml/experiments/${arm.experiment_id}/traces?selectedEvaluationId=${final.trace_id}`
      : null;
  const outside = final.out_of_scope_tables;
  const curatedOnly = final.routes.length > 0 && final.routes.every((route) => route.startsWith("genie:"));
  return (
    <>
      <div className="used">
        {final.routes.length === 0 && <span className="chip">Answered without an agent</span>}
        {final.routes.map((route) => (
          <span key={route} className="chip chip-route">
            <RouteIcon route={route} />
            {routeLabel(route)}
          </span>
        ))}
        {final.latency_s !== null && <span className="chip num">{final.latency_s.toFixed(1)} s</span>}
        {final.sql.length > 0 && (
          <button type="button" className="chip" aria-expanded={panel === "sql"} onClick={() => setPanel(panel === "sql" ? null : "sql")}>
            <Code size={14} />
            SQL ({final.sql.length})
          </button>
        )}
        {final.tables.length > 0 && (
          <button
            type="button"
            className={outside.length && panel !== "tables" ? "chip chip-bad" : "chip"}
            aria-expanded={panel === "tables"}
            onClick={() => setPanel(panel === "tables" ? null : "tables")}
          >
            <Table size={14} />
            {outside.length ? `${outside.length} of ${final.tables.length} tables outside the scope` : `Tables (${final.tables.length})`}
          </button>
        )}
        {genieLink && (
          <a className="chip" href={genieLink} target="_blank" rel="noreferrer">
            Open in Genie One <ArrowSquareOut size={13} />
          </a>
        )}
        {traceUrl && (
          <a className="chip" href={traceUrl} target="_blank" rel="noreferrer">
            Trace <ArrowSquareOut size={13} />
          </a>
        )}
      </div>
      {panel === "sql" && (
        <div className="drawer">
          {final.sql.map((statement, index) => (
            <pre key={index} className="sql">
              <CopyButton text={statement} label="Copy this SQL" className="sql-copy" />
              {statement}
            </pre>
          ))}
        </div>
      )}
      {panel === "tables" && (
        <div className="drawer">
          <ul className="table-chips">
            {final.tables.map((table) => (
              <li key={table} className={outside.includes(table) ? "chip chip-bad" : "chip"} title={table}>
                <code>{tableName(table)}</code>
                {outside.includes(table) && "outside the scope"}
              </li>
            ))}
          </ul>
        </div>
      )}
      {curatedOnly && final.sql.length === 0 && (
        <p className="muted small">A curated Genie Agent answered. Its SQL is in the trace, not in the reply.</p>
      )}
    </>
  );
}

function Rate({ reply, seq }: { reply: Reply; seq: number }) {
  const { rate } = useChat();
  const [form, setForm] = useState<Rating | null>(null);
  const [reasons, setReasons] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const commentId = useId();
  const current = reply.feedback?.rating ?? null;
  const ready = reply.saved && Boolean(reply.turnId);

  async function send(rating: Rating | null, picked: string[] = [], text: string | null = null) {
    setFailed(null);
    try {
      const logged = await rate(seq, reply.arm, rating, picked, text);
      setNote(rating === null ? "Rating removed" : logged ? "Saved, and added to the MLflow trace" : "Saved");
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
    }
  }

  function onThumb(rating: Rating) {
    if (current === rating) {
      setForm(null);
      void send(null);
      return;
    }
    if (rating === "up") {
      setForm(null);
      void send("up");
      return;
    }
    setReasons(reply.feedback?.reasons ?? []);
    setComment(reply.feedback?.comment ?? "");
    setForm("down");
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const rating = form ?? "up";
    setForm(null);
    void send(rating, rating === "down" ? reasons : [], comment.trim() || null);
  }

  return (
    <>
      <div className="rate">
        <button
          type="button"
          className="icon-button"
          aria-label="Good answer"
          title="Good answer"
          aria-pressed={current === "up"}
          disabled={!ready}
          onClick={() => onThumb("up")}
        >
          <ThumbsUp size={17} weight={current === "up" ? "fill" : "regular"} />
        </button>
        <button
          type="button"
          className="icon-button down"
          aria-label="Bad answer"
          title="Bad answer"
          aria-pressed={current === "down" || form === "down"}
          disabled={!ready}
          onClick={() => onThumb("down")}
        >
          <ThumbsDown size={17} weight={current === "down" ? "fill" : "regular"} />
        </button>
        <CopyButton text={reply.final?.answer ?? ""} label="Copy the answer" />
        <span className="rate-note" role="status">
          {failed ? (
            <span className="verdict-bad">Not saved: {failed}</span>
          ) : reply.saveError ? (
            "This answer could not be saved, so it cannot be rated."
          ) : !ready ? (
            "Saving the answer"
          ) : (
            note
          )}
        </span>
        {ready && current === "up" && form === null && (
          <button
            type="button"
            className="chip"
            onClick={() => {
              setComment(reply.feedback?.comment ?? "");
              setForm("up");
            }}
          >
            Add a note
          </button>
        )}
      </div>
      {form && (
        <form className="rate-form" onSubmit={onSubmit}>
          {form === "down" && (
            <fieldset className="reason-row">
              <legend>What went wrong?</legend>
              {REASONS.map((reason) => (
                <label key={reason} className="reason">
                  <input
                    type="checkbox"
                    checked={reasons.includes(reason)}
                    onChange={(event) =>
                      setReasons(event.target.checked ? [...reasons, reason] : reasons.filter((r) => r !== reason))
                    }
                  />
                  <span>{reason}</span>
                </label>
              ))}
            </fieldset>
          )}
          <label htmlFor={commentId}>{form === "down" ? "What should it have said?" : "What made it good?"}</label>
          <textarea
            id={commentId}
            className="text-input"
            rows={2}
            maxLength={2000}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
          <div className="row-actions">
            <button type="submit" className="btn btn-primary">
              Send feedback
            </button>
            <button type="button" className="btn" onClick={() => setForm(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </>
  );
}

export function ReplyView({ reply, seq, config, showWho }: { reply: Reply; seq: number; config: Config; showWho: boolean }) {
  const text = reply.final?.answer ?? reply.draft;
  return (
    <section className="reply" aria-label={`${ARM_NAME[reply.arm]} answer`} aria-busy={reply.status === "streaming"}>
      {showWho && (
        <div className="reply-who">
          <span className={`who-dot who-${reply.arm}`} aria-hidden="true">
            <ArmIcon arm={reply.arm} size={13} />
          </span>
          {ARM_NAME[reply.arm]}
        </div>
      )}
      <Thinking reply={reply} />
      {text.trim() && <Markdown text={text} writing={reply.status === "streaming" && !reply.draftDone} />}
      {reply.error && (
        <p className="reply-error" role="alert">
          <WarningCircle size={18} weight="fill" aria-hidden="true" />
          <span>
            {reply.final?.answer ? "The run stopped early. " : "No answer came back. "}
            {reply.error}
          </span>
        </p>
      )}
      {reply.final && reply.status !== "streaming" && (
        <>
          <Used reply={reply} config={config} />
          <Rate reply={reply} seq={seq} />
        </>
      )}
    </section>
  );
}
