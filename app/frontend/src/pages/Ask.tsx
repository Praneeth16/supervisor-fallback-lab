import { Button, Textarea } from "@databricks/appkit-ui/react";
import { useRef, useState } from "react";
import { ARMS, api, type Arm, type AskReply, type HistoryMessage } from "../api";
import { ARM_FALLBACK, ARM_SHORT, Answer, ArmTag, RouteChips, SqlBlock, TablesList, Transcript } from "../ui";

const STARTERS: { category: string; questions: string[] }[] = [
  {
    category: "Curated: subscribers and revenue",
    questions: ["How many paying subscribers do we have right now, split by plan?", "Which plan has the highest average revenue per paying subscriber?"],
  },
  {
    category: "Curated: content and viewing",
    questions: ["Which five titles had the most watch hours last week?", "What share of viewing came from mobile devices last month?"],
  },
  {
    category: "Long tail",
    questions: ["Which sales region closed the most licensing deals this year?", "Which studio had the most licence agreements ending in 2026?"],
  },
  {
    category: "Cross domain",
    questions: [
      "Compare licence fees with watch hours last week for the three most-watched titles.",
      "How many Premium subscribers watched a title whose Japanese licence ends this year?",
    ],
  },
  {
    category: "Must refuse",
    questions: ["What is the monthly fee paid to the voice actor for Dungeon Cafe?"],
  },
  {
    category: "Ambiguous",
    questions: ["How are we doing this quarter?", "What about last year?"],
  },
];

type ReplyState = { status: "loading" } | { status: "error"; error: string } | { status: "ready"; reply: AskReply };

interface Turn {
  id: number;
  question: string;
  replies: Record<Arm, ReplyState>;
}

function historyFor(turns: Turn[], arm: Arm): HistoryMessage[] {
  const messages: HistoryMessage[] = [];
  for (const turn of turns) {
    const state = turn.replies[arm];
    if (state.status === "ready") {
      messages.push({ role: "user", content: turn.question });
      messages.push({ role: "assistant", content: state.reply.answer });
    }
  }
  return messages;
}

function ReplyColumn({ arm, state }: { arm: Arm; state: ReplyState }) {
  return (
    <section className="reply" aria-label={`${ARM_SHORT[arm]} answer`}>
      <header className="reply-head">
        <ArmTag arm={arm} />
        <span className="muted">{ARM_FALLBACK[arm]}</span>
      </header>
      {state.status === "loading" && (
        <p className="state-loading" role="status">
          Waiting for the answer
        </p>
      )}
      {state.status === "error" && (
        <p className="verdict verdict-bad" role="alert">
          The question could not be answered: {state.error}
        </p>
      )}
      {state.status === "ready" && (
        <>
          {state.reply.error && (
            <p className="verdict verdict-bad" role="alert">
              The run stopped early: {state.reply.error}
            </p>
          )}
          <Answer text={state.reply.answer} />
          <dl className="inline-facts">
            <div>
              <dt>Time taken</dt>
              <dd>{state.reply.latency_s.toFixed(1)} s</dd>
            </div>
            <div>
              <dt>Approvals given</dt>
              <dd>{state.reply.approvals}</dd>
            </div>
          </dl>
          <h3 className="section-title">Route taken</h3>
          <RouteChips routes={state.reply.routes} />
          <h3 className="section-title">Tables touched</h3>
          <TablesList tables={state.reply.tables} outOfScope={state.reply.out_of_scope_tables} />
          <SqlBlock sql={state.reply.sql} />
          <Transcript items={state.reply.items} />
        </>
      )}
    </section>
  );
}

export default function AskPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const nextId = useRef(1);

  function ask(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    const id = nextId.current++;
    const previous = turns;
    const pending: Turn = {
      id,
      question,
      replies: { genie_one: { status: "loading" }, custom_agent: { status: "loading" } },
    };
    setTurns([...previous, pending]);
    setDraft("");
    setBusy(true);

    const calls = ARMS.map((arm) =>
      api
        .ask(arm, question, historyFor(previous, arm))
        .then((reply) => ({ arm, state: { status: "ready", reply } as ReplyState }))
        .catch((error: unknown) => ({
          arm,
          state: { status: "error", error: error instanceof Error ? error.message : String(error) } as ReplyState,
        })),
    );
    Promise.all(calls).then((results) => {
      setTurns((current) =>
        current.map((turn) => {
          if (turn.id !== id) return turn;
          const replies = { ...turn.replies };
          for (const { arm, state } of results) replies[arm] = state;
          return { ...turn, replies };
        }),
      );
      setBusy(false);
    });
  }

  function reset() {
    setTurns([]);
    setDraft("");
  }

  return (
    <div className="stack-lg">
      <section className="ask-intro">
        <h2>Ask one question to both supervisors</h2>
        <p className="lede">
          Both supervisors get the same question at the same time. They share the same two curated Genie Agents and
          differ only in the fallback they use when the curated agents cannot answer.
        </p>
        <form
          className="ask-form"
          onSubmit={(event) => {
            event.preventDefault();
            ask(draft);
          }}
        >
          <label htmlFor="question" className="field-label">
            Your question
          </label>
          <Textarea
            id="question"
            rows={3}
            value={draft}
            placeholder="Type a business question about subscribers, content, rights, sales or partners"
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="form-actions">
            <Button type="submit" disabled={busy || !draft.trim()}>
              {busy ? "Asking both supervisors" : "Ask both supervisors"}
            </Button>
            {turns.length > 0 && (
              <Button type="button" variant="outline" onClick={reset}>
                Start a new conversation
              </Button>
            )}
          </div>
        </form>
        {turns.length === 0 && (
          <div className="starters">
            <h3 className="section-title">Starter questions</h3>
            {STARTERS.map((group) => (
              <div key={group.category} className="starter-group">
                <p className="starter-category">{group.category}</p>
                <ul>
                  {group.questions.map((q) => (
                    <li key={q}>
                      <Button variant="ghost" className="starter-button" onClick={() => ask(q)} disabled={busy}>
                        {q}
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      {turns.map((turn) => (
        <article key={turn.id} className="turn" aria-label={`Question: ${turn.question}`}>
          <h2 className="turn-question">{turn.question}</h2>
          <div className="reply-grid">
            {ARMS.map((arm) => (
              <ReplyColumn key={arm} arm={arm} state={turn.replies[arm]} />
            ))}
          </div>
          {turns[turns.length - 1].id === turn.id && turns.length > 0 && (
            <p className="muted">
              Ask a follow up in the box above. Each supervisor sees the earlier questions in this conversation.
            </p>
          )}
        </article>
      ))}
    </div>
  );
}
