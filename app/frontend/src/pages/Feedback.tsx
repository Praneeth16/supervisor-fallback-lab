import { ThumbsDown, ThumbsUp } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { ARMS, type Arm } from "../api";
import { chatApi, type FeedbackSummary } from "../chatApi";
import { ARM_NAME } from "../chat/ReplyView";
import { pct } from "../format";
import { useLoad } from "../hooks";
import { StateBlock } from "../ui";

function Preference({ votes }: { votes: FeedbackSummary["preference"] }) {
  const total = votes.genie_one + votes.custom_agent + votes.same;
  if (total === 0) {
    return (
      <p className="muted">
        No votes yet. Start a chat with Compare both, and a vote bar appears under each pair of answers.
      </p>
    );
  }
  const parts: { key: keyof typeof votes; label: string; color: string }[] = [
    { key: "genie_one", label: "Genie One", color: "var(--arm-genie-one)" },
    { key: "custom_agent", label: "Custom agent", color: "var(--arm-custom-agent)" },
    { key: "same", label: "About the same", color: "var(--line-strong)" },
  ];
  return (
    <>
      <div className="split-bar" role="img" aria-label={parts.map((p) => `${p.label} ${votes[p.key]}`).join(", ")}>
        {parts.map((part) => (
          <span key={part.key} style={{ width: `${(votes[part.key] / total) * 100}%`, background: part.color }} />
        ))}
      </div>
      <dl className="fact-row" style={{ marginTop: "0.8rem" }}>
        {parts.map((part) => (
          <div key={part.key}>
            <dt>{part.label}</dt>
            <dd className="num">{votes[part.key]}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}

export default function FeedbackPage() {
  const summary = useLoad(() => chatApi.feedbackSummary(), []);
  return (
    <div className="stack-lg">
      <section className="page-head">
        <h2>Feedback</h2>
        <p className="lede">
          Every thumbs up, thumbs down and vote given in the chat, kept under the name of the person who gave it. A
          rating is also added to the supervisor's MLflow trace, so it sits next to the steps of that answer.
        </p>
      </section>
      <StateBlock
        state={summary.state}
        empty="Nobody has asked a question in the chat yet. Ask one, then rate the answer with the thumbs under it."
        isEmpty={(data) => data.totals.answers === 0}
        onRetry={summary.reload}
      >
        {(data) => (
          <>
            <section className="stack">
              <h3 className="section-title">Ratings by assistant</h3>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Assistant</th>
                    <th className="right">Answers</th>
                    <th className="right">Rated</th>
                    <th className="right">Thumbs up</th>
                    <th className="right">Thumbs down</th>
                    <th className="right">Share up</th>
                    <th>Reasons given with a thumbs down</th>
                  </tr>
                </thead>
                <tbody>
                  {ARMS.map((arm: Arm) => {
                    const row = data.arms[arm];
                    const reasons = Object.entries(row.down_reasons);
                    return (
                      <tr key={arm}>
                        <td>
                          <strong>{ARM_NAME[arm]}</strong>
                        </td>
                        <td className="right">{row.answers}</td>
                        <td className="right">{row.rated}</td>
                        <td className="right">{row.up}</td>
                        <td className="right">{row.down}</td>
                        <td className="right">{row.rated ? pct(row.up_rate) : "No ratings"}</td>
                        <td>
                          {reasons.length === 0 ? (
                            <span className="muted">None</span>
                          ) : (
                            reasons.map(([reason, n]) => `${reason} (${n})`).join(", ")
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>

            <section className="stack">
              <h3 className="section-title">Which answer people preferred</h3>
              <p className="muted">Votes from chats where both assistants answered the same question.</p>
              <Preference votes={data.preference} />
            </section>

            <section className="stack">
              <h3 className="section-title">By person</h3>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Person</th>
                    <th className="right">Questions</th>
                    <th className="right">Thumbs up</th>
                    <th className="right">Thumbs down</th>
                    <th className="right">Voted Genie One</th>
                    <th className="right">Voted custom agent</th>
                    <th className="right">Voted the same</th>
                  </tr>
                </thead>
                <tbody>
                  {data.people.map((person) => (
                    <tr key={person.user_email}>
                      <td>{person.user_email}</td>
                      <td className="right">{person.questions}</td>
                      <td className="right">{person.up}</td>
                      <td className="right">{person.down}</td>
                      <td className="right">{person.votes.genie_one}</td>
                      <td className="right">{person.votes.custom_agent}</td>
                      <td className="right">{person.votes.same}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="stack">
              <h3 className="section-title">Latest ratings</h3>
              {data.recent.length === 0 ? (
                <p className="muted">No answer has been rated yet.</p>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Rating</th>
                      <th>Question and answer</th>
                      <th>Assistant</th>
                      <th>Rated by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent.map((row) => (
                      <tr key={`${row.turn_id}-${row.rated_by}`}>
                        <td>
                          {row.rating === "up" ? (
                            <span className="pill pill-good">
                              <ThumbsUp size={13} weight="fill" /> Up
                            </span>
                          ) : (
                            <span className="pill pill-bad">
                              <ThumbsDown size={13} weight="fill" /> Down
                            </span>
                          )}
                        </td>
                        <td style={{ maxWidth: "60ch" }}>
                          <strong>{row.question}</strong>
                          <p className="quote">{row.answer.length > 220 ? `${row.answer.slice(0, 220)}…` : row.answer}</p>
                          {(row.reasons.length > 0 || row.comment) && (
                            <p className="small" style={{ marginTop: "0.3rem" }}>
                              {row.reasons.join(", ")}
                              {row.reasons.length > 0 && row.comment ? ". " : ""}
                              {row.comment && <em>{row.comment}</em>}
                            </p>
                          )}
                        </td>
                        <td>{ARM_NAME[row.arm]}</td>
                        <td>{row.rated_by}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <section className="panel stack">
              <h3 className="section-title" style={{ marginTop: 0 }}>
                Turn good answers into benchmark questions
              </h3>
              <p className="muted" style={{ maxWidth: "75ch" }}>
                Feedback is about live use and stays here, next to the traces. The benchmark is a separate, fixed set of
                questions with reference answers. Answers with a thumbs up are a cheap source of new questions for it:{" "}
                <code>make gold FROM=feedback</code> drafts them, a larger model writes the reference SQL, and a person
                who knows the data checks each one. See <Link to="/benchmark/questions">Questions and ground truth</Link>.
              </p>
            </section>
          </>
        )}
      </StateBlock>
    </div>
  );
}
