import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@databricks/appkit-ui/react";
import { REPLICATE_STEPS } from "../data/replicate";

export default function ReplicatePage() {
  return (
    <div className="stack-lg">
      <section className="page-head">
        <h2>Replicate the lab</h2>
        <p className="lede">
          Two supervisors answer the same questions. Both route to the same two curated Genie Agents. They differ only in
          the fallback used when those agents cannot answer.
        </p>
      </section>

      <section className="stack" aria-labelledby="arch-heading">
        <h3 id="arch-heading" className="section-title">
          Architecture of the two arms
        </h3>
        <ArchitectureDiagram />
        <div className="arm-explainers">
          <Card>
            <CardHeader>
              <CardTitle>
                <span className="arm-tag arm-genie_one">Supervisor A</span>
              </CardTitle>
              <CardDescription>Control point: instructions and skills</CardDescription>
            </CardHeader>
            <CardContent>
              <p>
                The fallback is the managed Genie One MCP server. Its scope comes from instructions and skills in the
                workspace. Those rules are followed by the agent and are not enforced by code.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>
                <span className="arm-tag arm-custom_agent">Supervisor B</span>
              </CardTitle>
              <CardDescription>Control point: table allowlist in code</CardDescription>
            </CardHeader>
            <CardContent>
              <p>
                The fallback is a custom text to SQL agent deployed as a Databricks App. Each statement is parsed before it
                runs, and a table outside the allowlist is blocked.
              </p>
            </CardContent>
          </Card>
        </div>
      </section>

      <section className="stack" aria-labelledby="steps-heading">
        <h3 id="steps-heading" className="section-title">
          Steps to run the lab again
        </h3>
        <ol className="steps">
          {REPLICATE_STEPS.map((step) => (
            <li key={step.command}>
              <p className="step-title">{step.title}</p>
              <pre className="code-block">{step.command}</pre>
              <p className="muted">{step.note}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function ArchitectureDiagram() {
  return (
    <figure className="diagram">
      <svg viewBox="0 0 1000 500" role="img" aria-labelledby="diagram-title diagram-desc" className="diagram-svg">
        <title id="diagram-title">Architecture of the two supervisor arms</title>
        <desc id="diagram-desc">
          The lab app sends each question to both supervisors as the signed-in user. Each supervisor sends curated
          questions to the two Genie Agents and everything else to its fallback. Supervisor A calls Genie One through
          Unity Gateway; Genie One can read any schema the user can read, including the off-limits one. Supervisor B
          calls the custom agent, whose SQL guard blocks every table outside the allowlist before the query reaches
          Unity Gateway.
        </desc>
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" className="arrow-head" />
          </marker>
          <marker id="arrow-risk" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" className="arrow-head-risk" />
          </marker>
        </defs>

        <g className="edge">
          <path d="M140,235 H160 V90 H180" markerEnd="url(#arrow)" />
          <path d="M140,265 H160 V410 H180" markerEnd="url(#arrow)" />
          <path d="M350,90 H410" markerEnd="url(#arrow)" />
          <path d="M350,410 H410" markerEnd="url(#arrow)" />
          <path d="M265,125 V235 H410" markerEnd="url(#arrow)" />
          <path d="M265,375 V265 H410" markerEnd="url(#arrow)" />
          <path d="M600,90 H650" markerEnd="url(#arrow)" />
          <path d="M600,410 H650" markerEnd="url(#arrow)" />
          <path d="M600,250 H830" markerEnd="url(#arrow)" />
          <path d="M715,125 V235 H830" markerEnd="url(#arrow)" />
          <path d="M715,365 V265 H830" markerEnd="url(#arrow)" />
        </g>
        <g className="edge edge-risk">
          <path d="M780,90 H830" markerEnd="url(#arrow-risk)" />
          <path d="M505,375 V335" />
          <path d="M497,327 L513,343 M513,327 L497,343" />
        </g>

        <g className="edge-label">
          <text x="380" y="80" textAnchor="middle">MCP</text>
          <text x="380" y="400" textAnchor="middle">MCP</text>
          <text x="380" y="432" textAnchor="middle">approval</text>
          <text x="805" y="80" textAnchor="middle" className="edge-label-risk">open</text>
          <text x="522" y="340" className="edge-label-risk">guard blocks other tables</text>
          <text x="340" y="228" textAnchor="middle">curated questions</text>
        </g>

        <g>
          <rect x="20" y="215" width="120" height="70" rx="8" className="node node-neutral" />
          <text x="80" y="245" textAnchor="middle" className="node-title">Lab app</text>
          <text x="80" y="265" textAnchor="middle" className="node-sub">as the user</text>
        </g>

        <g>
          <rect x="180" y="55" width="170" height="70" rx="8" className="node node-genie_one" />
          <text x="265" y="85" textAnchor="middle" className="node-title">Supervisor A</text>
          <text x="265" y="105" textAnchor="middle" className="node-sub">scope: instructions</text>
        </g>
        <g>
          <rect x="180" y="375" width="170" height="70" rx="8" className="node node-custom_agent" />
          <text x="265" y="405" textAnchor="middle" className="node-title">Supervisor B</text>
          <text x="265" y="425" textAnchor="middle" className="node-sub">same routing rules</text>
        </g>

        <g>
          <rect x="410" y="55" width="190" height="70" rx="8" className="node node-genie_one" />
          <text x="505" y="85" textAnchor="middle" className="node-title">Genie One</text>
          <text x="505" y="105" textAnchor="middle" className="node-sub">scope: skill and instructions</text>
        </g>
        <g>
          <rect x="410" y="215" width="190" height="70" rx="8" className="node node-neutral" />
          <text x="505" y="245" textAnchor="middle" className="node-title">Two Genie Agents</text>
          <text x="505" y="265" textAnchor="middle" className="node-sub">only their attached tables</text>
        </g>
        <g>
          <rect x="410" y="375" width="190" height="70" rx="8" className="node node-custom_agent" />
          <text x="505" y="405" textAnchor="middle" className="node-title">Custom agent app</text>
          <text x="505" y="425" textAnchor="middle" className="node-sub">scope: SQL guard in code</text>
        </g>

        <g>
          <rect x="650" y="55" width="130" height="70" rx="8" className="node node-neutral" />
          <text x="715" y="85" textAnchor="middle" className="node-title">Unity Gateway</text>
          <text x="715" y="105" textAnchor="middle" className="node-sub">Genie One MCP</text>
        </g>
        <g>
          <rect x="650" y="365" width="130" height="90" rx="8" className="node node-neutral" />
          <text x="715" y="395" textAnchor="middle" className="node-title">Unity Gateway</text>
          <text x="715" y="415" textAnchor="middle" className="node-sub">SQL MCP</text>
          <text x="715" y="435" textAnchor="middle" className="node-sub">model service</text>
        </g>

        <g>
          <rect x="830" y="55" width="150" height="70" rx="8" className="node node-risk" />
          <text x="905" y="85" textAnchor="middle" className="node-title">Off limits</text>
          <text x="905" y="105" textAnchor="middle" className="node-sub">talent schema</text>
        </g>
        <g>
          <rect x="830" y="205" width="150" height="90" rx="8" className="node node-neutral" />
          <text x="905" y="240" textAnchor="middle" className="node-title">In scope</text>
          <text x="905" y="260" textAnchor="middle" className="node-sub">curated schemas</text>
          <text x="905" y="278" textAnchor="middle" className="node-sub">fallback schemas</text>
        </g>
      </svg>
      <figcaption className="muted small">
        Every query runs as the signed-in user. In arm A nothing technical stops Genie One from reading a table the user
        can read, so the scope depends on text. In arm B the guard checks each statement and blocks tables outside the
        allowlist before the query is sent. Calls through Unity Gateway are logged for both arms.
      </figcaption>
    </figure>
  );
}
