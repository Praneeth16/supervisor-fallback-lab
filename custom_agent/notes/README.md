# Notes from the data owner

The agent's table descriptions are generated from Unity Catalog every time `make agent` runs, so
anything you type into `custom_agent/context/` is lost on the next run. Put what Unity Catalog does
not hold in this folder instead. `scripts/sync_context.py` merges it in on every run.

## Notes for one table

Create `<schema>.<table>.md` in this folder, without the catalog, for example
`hoshi_sales.campaign.md`. Upper and lower case do not matter. The text is added to that table's
description under the heading "Notes from the data owner", so the agent reads it whenever it reads
the table.

Good things to write down:

- What each value of a category column means, and which values to leave out of a count.
- Exceptions, for example "rows before 2024 have no region".
- How your team defines a metric on this table.
- Which column to join on when two look alike.

Keep it short. The agent reads the whole file every time it opens the table.

## Rules for all tables

Create `RULES.md` in this folder. Each line is one rule. The lines are added to the rules the agent
gets with every question. Headings and empty lines are skipped.

## Check the result

Run `.venv/bin/python scripts/sync_context.py` and read the last lines it prints. It says how many
notes files were used, and it warns about a notes file whose name matches no table in scope. The
merged text is in `custom_agent/context/tables/` and `custom_agent/context/RULES.md`.

The Genie One fallback does not read this folder. If you compare the two fallbacks, put the same
facts into the Genie One skill, or the comparison is no longer equal.
