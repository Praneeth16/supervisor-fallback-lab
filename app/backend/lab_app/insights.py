"""What the saved chats say: how people rated each assistant, and which tables the fallback is asked about most.

Both functions take the rows of `chat_store.rated_turns()`, so the same code serves Delta and fixtures.
"""

from .summary import rate

FALLBACK_ROUTES = ("genie_one", "fallback_agent")


def _is_fallback(row: dict) -> bool:
    return any(route in FALLBACK_ROUTES for route in row["routes"])


def _is_curated(row: dict) -> bool:
    return any(route.startswith("genie:") for route in row["routes"])


def _turns(rows: list[dict]) -> list[dict]:
    """One row for each turn. `rated_turns` repeats a turn once for each person who rated it."""
    seen: dict[str, dict] = {}
    for row in rows:
        seen.setdefault(row["turn_id"], row)
    return list(seen.values())


def feedback_summary(rows: list[dict], votes: list[dict], arms: tuple[str, ...]) -> dict:
    turns = _turns(rows)
    rated = [r for r in rows if r["rating"] in ("up", "down")]
    by_arm = {}
    for arm in arms:
        mine = [r for r in rated if r["arm"] == arm]
        up = sum(r["rating"] == "up" for r in mine)
        reasons: dict[str, int] = {}
        for row in mine:
            for reason in row["reasons"] if row["rating"] == "down" else []:
                reasons[reason] = reasons.get(reason, 0) + 1
        by_arm[arm] = {
            "answers": sum(t["arm"] == arm for t in turns),
            "rated": len({r["turn_id"] for r in mine}),
            "up": up,
            "down": len(mine) - up,
            "up_rate": rate(r["rating"] == "up" for r in mine),
            "down_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        }

    people: dict[str, dict] = {}

    def person(email: str) -> dict:
        return people.setdefault(
            email,
            {"user_email": email, "questions": 0, "up": 0, "down": 0,
             "votes": {"genie_one": 0, "custom_agent": 0, "same": 0}},
        )  # fmt: skip

    for email in {t["user_email"] for t in turns}:
        asked = {(t["conversation_id"], t["question"]) for t in turns if t["user_email"] == email}
        person(email)["questions"] = len(asked)
    for row in rated:
        person(row["rated_by"])[row["rating"]] += 1
    preference = {"genie_one": 0, "custom_agent": 0, "same": 0}
    for vote in votes:
        if vote["choice"] in preference:
            preference[vote["choice"]] += 1
            person(vote["user_email"])["votes"][vote["choice"]] += 1

    recent = sorted(rated, key=lambda r: r["rated_at"] or "", reverse=True)[:60]
    return {
        "arms": by_arm,
        "preference": preference,
        "people": sorted(people.values(), key=lambda p: (-p["questions"], p["user_email"])),
        "recent": [
            {
                k: r[k]
                for k in (
                    "turn_id",
                    "conversation_id",
                    "arm",
                    "question",
                    "answer",
                    "rating",
                    "reasons",
                    "comment",
                    "rated_by",
                    "rated_at",
                    "routes",
                )
            }
            for r in recent
        ],  # fmt: skip
        "totals": {"answers": len(turns), "ratings": len(rated), "votes": sum(preference.values())},
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def activity(rows: list[dict], arms: tuple[str, ...], limit: int = 200) -> dict:
    """What people asked in the chat: totals for each assistant and the latest answers."""
    turns = _turns(rows)
    ratings: dict[str, str] = {}
    for row in rows:
        if row["rating"] in ("up", "down"):
            # Several people may rate one answer. A thumbs down from anyone is the one to look at.
            ratings[row["turn_id"]] = "down" if "down" in (ratings.get(row["turn_id"]), row["rating"]) else "up"
    by_arm = {}
    for arm in arms:
        mine = [t for t in turns if t["arm"] == arm]
        by_arm[arm] = {
            "answers": len(mine),
            "people": len({t["user_email"] for t in mine}),
            "latency_p50_s": _median([t["latency_s"] for t in mine if t["latency_s"] is not None]),
            "errors": sum(bool(t["error"]) for t in mine),
            "out_of_scope": sum(bool(t["out_of_scope_tables"]) for t in mine),
            "to_fallback": sum(_is_fallback(t) for t in mine),
            "up": sum(ratings.get(t["turn_id"]) == "up" for t in mine),
            "down": sum(ratings.get(t["turn_id"]) == "down" for t in mine),
        }
    latest = sorted(turns, key=lambda t: t["created_at"] or "", reverse=True)[:limit]
    return {
        "arms": by_arm,
        "totals": {
            "answers": len(turns),
            "questions": len({(t["conversation_id"], t["question"]) for t in turns}),
            "people": len({t["user_email"] for t in turns}),
        },
        "turns": [
            {
                **{
                    k: t.get(k)
                    for k in (
                        "turn_id",
                        "conversation_id",
                        "user_email",
                        "arm",
                        "mode",
                        "question",
                        "routes",
                        "tables",
                        "out_of_scope_tables",
                        "latency_s",
                        "error",
                        "created_at",
                        "trace_id",
                    )
                },
                "rating": ratings.get(t["turn_id"]),
            }
            for t in latest
        ],  # fmt: skip
    }


def _owner(table: str, scope: dict, schema_prefix: str) -> str:
    """Who a table belongs to in the lab's scope: the fallback, a curated agent, or nobody."""
    parts = table.split(".")
    if len(parts) < 2:
        return "outside"
    schema = parts[-2]
    domain = schema[len(schema_prefix) :] if schema_prefix and schema.startswith(schema_prefix) else schema
    if domain in scope.get("fallback", []):
        return "fallback"
    for agent, domains in scope.get("genie_agents", {}).items():
        if domain in domains:
            return f"curated:{agent}"
    return "outside"


def fallback_demand(rows: list[dict], scope: dict, schema_prefix: str, min_questions: int, min_people: int) -> dict:
    """Tables the fallback was asked about, most asked first.

    A table becomes a candidate for a curated Genie Agent when at least `min_questions` questions from
    at least `min_people` people reached the fallback and used it. A question asked to both assistants
    in compare mode counts once.
    """
    turns = _turns(rows)
    questions = {(t["conversation_id"], t["question"]) for t in turns}
    fallback = [t for t in turns if _is_fallback(t)]
    curated_only = [t for t in turns if _is_curated(t) and not _is_fallback(t)]
    ratings: dict[str, list[str]] = {}
    for row in rows:
        if row["rating"] in ("up", "down"):
            ratings.setdefault(row["turn_id"], []).append(row["rating"])

    tables: dict[str, dict] = {}
    for turn in fallback:
        for table in turn["tables"]:
            entry = tables.setdefault(
                table,
                {"table": table, "owner": _owner(table, scope, schema_prefix), "asked": set(), "people": set(),
                 "arms": set(), "up": 0, "down": 0, "last_asked": "", "examples": []},
            )  # fmt: skip
            key = (turn["conversation_id"], turn["question"])
            if turn["question"] not in entry["examples"] and len(entry["examples"]) < 3:
                entry["examples"].append(turn["question"])
            entry["asked"].add(key)
            entry["people"].add(turn["user_email"])
            entry["arms"].add(turn["arm"])
            entry["last_asked"] = max(entry["last_asked"], turn["created_at"] or "")
            for rating in ratings.get(turn["turn_id"], []):
                entry[rating] += 1

    out = []
    for entry in tables.values():
        n_questions, n_people = len(entry["asked"]), len(entry["people"])
        out.append(
            {
                "table": entry["table"],
                "owner": entry["owner"],
                "questions": n_questions,
                "people": n_people,
                "arms": sorted(entry["arms"]),
                "up": entry["up"],
                "down": entry["down"],
                "last_asked": entry["last_asked"] or None,
                "examples": entry["examples"],
                "candidate": entry["owner"] == "fallback" and n_questions >= min_questions and n_people >= min_people,
            }
        )
    out.sort(key=lambda e: (-e["questions"], -e["people"], e["table"]))
    fallback_questions = {(t["conversation_id"], t["question"]) for t in fallback}
    curated_questions = {(t["conversation_id"], t["question"]) for t in curated_only} - fallback_questions
    return {
        "tables": out,
        "rule": {"min_questions": min_questions, "min_people": min_people},
        "totals": {
            "questions": len(questions),
            "to_fallback": len(fallback_questions),
            "to_curated": len(curated_questions),
            "no_agent": len(questions - fallback_questions - curated_questions),
            "candidates": sum(e["candidate"] for e in out),
        },
    }
