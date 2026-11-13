import { ArrowSquareOut, ThumbsDown, ThumbsUp } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { ARMS, request, type Arm, type Config } from "../api";
import { ARM_NAME } from "../chat/ReplyView";
import { routeLabel, seconds } from "../format";
import { useLoad } from "../hooks";
import { StateBlock } from "../ui";

interface ArmActivity {
  answers: number;
  people: number;
  latency_p50_s: number | null;
  errors: number;
  out_of_scope: number;
  to_fallback: number;
  up: number;
  down: number;
}

interface ActivityTurn {
  turn_id: string;
  conversation_id: string;
  user_email: string;
  arm: Arm;
  mode: string;
  question: string;
  routes: string[];
  tables: string[];
  out_of_scope_tables: string[];
  latency_s: number | null;
  error: string | null;
  created_at: string;
  trace_id: string | null;
  rating: "up" | "down" | null;
}

interface Activity {
  arms: Record<Arm, ArmActivity>;
  totals: { answers: number; questions: number; people: number };
  turns: ActivityTurn[];
}

function when(value: string): string {
  const date = new Date(value.replace(" ", "T") + "Z");
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function MonitorPage({ config }: { config: Config }) {
  const activity = useLoad(() => request<Activity>("/api/monitor/activity"), []);
  const experiments = Object.fromEntries(config.arms.map((arm) => [arm.key, arm.experiment_id]));

  function traceUrl(turn: ActivityTurn): string | null {
    const experiment = experiments[turn.arm];
    if (!turn.trace_id || !experiment || !config.workspace_host || config.fixtures) return null;
    return `${config.workspace_host}/ml/experiments/${experiment}/traces?selectedEvaluationId=${turn.trace_id}`;
  }

  return (
    <div className="stack-lg">
      <section className="page-head">
        <h2>Activity and traces</h2>
        <p className="lede">
          Every question asked in the chat, by anyone. Each answer has an MLflow trace with the supervisor's steps, and
          a thumbs up or down is stored on that trace. This is live use. The benchmark is separate and has its own
          questions with reference answers.
        </p>
      </section>
      <StateBlock
        state={activity.state}
        empty="Nobody has asked a question in the chat yet. Answers appear here as soon as they are saved."
        isEmpty={(data) => data.totals.answers === 0}
        onRetry={activity.reload}
      >
        {(data) => (
          <>
            <section className="stack">
              <dl className="fact-row">
                <div>
                  <dt>Questions</dt>
                  <dd className="num">{data.totals.questions}</dd>
                </div>
                <div>
                  <dt>Answers</dt>
                  <dd className="num">{data.totals.answers}</dd>
                </div>
                <div>
                  <dt>People</dt>
                  <dd className="num">{data.totals.people}</dd>
                </div>
              </dl>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Assistant</th>
                    <th className="right">Answers</th>
                    <th className="right">People</th>
                    <th className="right">Median time</th>
                    <th className="right">Used the fallback</th>
                    <th className="right">Read outside the scope</th>
                    <th className="right">Errors</th>
                    <th className="right">Thumbs up</th>
                    <th className="right">Thumbs down</th>
                  </tr>
                </thead>
                <tbody>
                  {ARMS.map((arm) => {
                    const row = data.arms[arm];
                    return (
                      <tr key={arm}>
                        <td>
                          <strong>{ARM_NAME[arm]}</strong>
                        </td>
                        <td className="right">{row.answers}</td>
                        <td className="right">{row.people}</td>
                        <td className="right">{row.answers ? seconds(row.latency_p50_s) : "No answers"}</td>
                        <td className="right">{row.to_fallback}</td>
                        <td className="right">
                          {row.out_of_scope ? <span className="bad-text">{row.out_of_scope}</span> : 0}
                        </td>
                        <td className="right">{row.errors}</td>
                        <td className="right">{row.up}</td>
                        <td className="right">{row.down}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>

            <section className="stack">
              <h3 className="section-title">Latest answers</h3>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Question</th>
                    <th>Assistant</th>
                    <th>Answered by</th>
                    <th className="right">Time</th>
                    <th>Rating</th>
                    <th>Trace</th>
                  </tr>
                </thead>
                <tbody>
                  {data.turns.map((turn) => {
                    const url = traceUrl(turn);
                    return (
                      <tr key={turn.turn_id}>
                        <td style={{ whiteSpace: "nowrap" }}>{when(turn.created_at)}</td>
                        <td style={{ maxWidth: "46ch" }}>
                          {turn.question.length > 140 ? `${turn.question.slice(0, 140)}…` : turn.question}
                          <p className="quote">{turn.user_email}</p>
                          {turn.out_of_scope_tables.length > 0 && (
                            <p className="small bad-text">Read outside the scope: {turn.out_of_scope_tables.join(", ")}</p>
                          )}
                          {turn.error && <p className="small bad-text">{turn.error.slice(0, 160)}</p>}
                        </td>
                        <td className="nowrap">{turn.arm === "genie_one" ? "Genie One" : "Custom agent"}</td>
                        <td>{turn.routes.length ? turn.routes.map(routeLabel).join(", ") : <span className="muted">No agent</span>}</td>
                        <td className="right">{turn.latency_s === null ? "" : seconds(turn.latency_s)}</td>
                        <td>
                          {turn.rating === "up" && (
                            <span className="pill pill-good">
                              <ThumbsUp size={13} weight="fill" /> Up
                            </span>
                          )}
                          {turn.rating === "down" && (
                            <span className="pill pill-bad">
                              <ThumbsDown size={13} weight="fill" /> Down
                            </span>
                          )}
                          {!turn.rating && <span className="muted">Not rated</span>}
                        </td>
                        <td className="nowrap">
                          {url ? (
                            <a href={url} target="_blank" rel="noreferrer" className="chip">
                              Open <ArrowSquareOut size={13} />
                            </a>
                          ) : (
                            <span className="muted">{turn.trace_id ? "In MLflow" : "None"}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="muted small">
                Ratings in detail are under <Link to="/monitor/feedback">Feedback</Link>. Tables the fallback is asked about
                are under <Link to="/monitor/demand">Fallback demand</Link>.
              </p>
            </section>
          </>
        )}
      </StateBlock>
    </div>
  );
}
