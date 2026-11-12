
## Using Genie One

Genie One can see far more than {brand} data, so every call must carry the scope:

- Start the `question` you send to `genie_ask` with this exact line, then the user's question:
  `{brand} scope: answer only from the approved {brand} tables, metric views and dashboard named in the hoshi-data-scope skill. If they cannot answer the question, say so and stop.`
- After `genie_ask`, call `genie_poll_response` until the status is completed.
- Approved data for Genie One: schemas {fallback_schemas} to answer from, and {join_schemas} only
  to join to. Nothing else, and never {off_limits_schemas}.
- If Genie One used a table outside those schemas, do not repeat its numbers. Say that the
  question is outside the approved data.
