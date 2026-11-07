"""Build pair-level weakly supervised labels from SF name *strings*.

Live warehouse facts (2026-09): ~77,399 SF name-only `court_party` defendants,
0 human `match_decision` rows, ~40 `system:suggestion` queue cards. Those
suggestion cards are **not** link labels.

Training labels in this MVP are synthetic pair labels:
  - positives: exact same string, or light format variants (case / comma vs
    space / dropped middle)
  - near-duplicate negatives: same last name, different first
  - hard negatives: different last names

This does **not** invent court cases, charges, DOB, or `court_party` rows.
Human GT (when present) lives in `gold.name_match_eval`: `link`/`reject` only;
`leave_in_review` and `system:suggestion` are never ground truth.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urljoin

from ml.name_match.constants import (
    DECISION_TABLE,
    LABEL_HUMAN_LINK,
    LABEL_HUMAN_REJECT,
    LABEL_SOURCE_HUMAN,
    LABEL_SOURCE_SYNTHETIC,
    LABEL_SYNTHETIC_EXACT_POSITIVE,
    LABEL_SYNTHETIC_HARD_NEGATIVE,
    LABEL_SYNTHETIC_NEAR_DUP_NEGATIVE,
    LABEL_SYNTHETIC_NEAR_POSITIVE,
    PARTY_TABLE,
    REVIEW_STATUS_HUMAN,
    REVIEW_STATUS_SUGGESTION,
    SOURCE_SYSTEM,
    STATE_CODE,
    SUGGESTION_EXPERIMENT_TAG,
    EVAL_TABLE,
    LABEL_LEAVE_IN_REVIEW,
    LABEL_LINK,
    LABEL_REJECT,
)
from silver.transforms.match_review_sketch import (
    norm_name_token,
    parse_subject_name,
)

# Documented synthetic fixtures — not live defendants (see SF_RESEARCH.md).
SYNTHETIC_FIXTURE_NAMES: tuple[dict[str, str | None], ...] = (
    {
        "raw_name": "JANE Q PUBLIC",
        "name_last": "PUBLIC",
        "name_first": "JANE",
        "name_middle": "Q",
    },
    {
        "raw_name": "JOHN MARSHALL FIXTURE",
        "name_last": "FIXTURE",
        "name_first": "JOHN",
        "name_middle": "MARSHALL",
    },
    {
        "raw_name": "LUIS SINGLETOKENLAST",
        "name_last": None,
        "name_first": None,
        "name_middle": None,
    },
    {
        "raw_name": "FIXTURE, LASTCOMMA FIRST",
        "name_last": "FIXTURE",
        "name_first": "LASTCOMMA",
        "name_middle": "FIRST",
    },
    {
        "raw_name": "A B C D FOURTOKEN",
        "name_last": "FOURTOKEN",
        "name_first": "A",
        "name_middle": "B C D",
    },
    {
        "raw_name": "MARIA GARCIA",
        "name_last": "GARCIA",
        "name_first": "MARIA",
        "name_middle": None,
    },
    {
        "raw_name": "ROBERT GARCIA",
        "name_last": "GARCIA",
        "name_first": "ROBERT",
        "name_middle": None,
    },
    {
        "raw_name": "ROBERT SMITH",
        "name_last": "SMITH",
        "name_first": "ROBERT",
        "name_middle": None,
    },
    {
        "raw_name": "ZELDA PUBLIC",
        "name_last": "PUBLIC",
        "name_first": "ZELDA",
        "name_middle": None,
    },
    {
        "raw_name": "PUBLIC, JANE Q",
        "name_last": "PUBLIC",
        "name_first": "JANE",
        "name_middle": "Q",
    },
)


SF_PARTY_NAME_SQL = f"""
SELECT
  raw_name,
  name_last,
  name_first,
  name_middle,
  concat_ws('|', source_system, state_code, source_record_id, party_role, party_ordinal) AS party_key
FROM {PARTY_TABLE}
WHERE source_system = '{SOURCE_SYSTEM}'
  AND state_code = '{STATE_CODE}'
  AND party_role IN ('defendant', 'aka')
  AND raw_name IS NOT NULL
  AND trim(raw_name) != ''
"""

LABEL_INVENTORY_SQL = f"""
SELECT
  coalesce(review_status, '') AS review_status,
  coalesce(actor, '') AS actor,
  count(*) AS n
FROM {DECISION_TABLE}
WHERE experiment_tag = '{SUGGESTION_EXPERIMENT_TAG}'
   OR source_system = '{SOURCE_SYSTEM}'
GROUP BY 1, 2
"""

HUMAN_LABEL_SQL = f"""
SELECT
  subject_ref,
  subject_name,
  raw_name AS party_raw_name,
  name_last AS party_name_last,
  name_first AS party_name_first,
  name_middle AS party_name_middle,
  party_key,
  confidence_band,
  review_status,
  actor
FROM {DECISION_TABLE}
WHERE review_status = '{REVIEW_STATUS_HUMAN}'
  AND (experiment_tag = '{SUGGESTION_EXPERIMENT_TAG}' OR source_system = '{SOURCE_SYSTEM}')
"""

EVAL_TABLE_SQL = f"""
SELECT
  subject_ref,
  party_key,
  label,
  source_system,
  state_code,
  labeled_at,
  actor,
  decision_id,
  confidence_band,
  experiment_tag,
  subject_name,
  raw_name AS party_raw_name,
  name_last AS party_name_last,
  name_first AS party_name_first,
  name_middle AS party_name_middle,
  party_role,
  review_status
FROM {EVAL_TABLE}
"""


@dataclass(frozen=True)
class NameRecord:
    raw_name: str
    name_last: str | None = None
    name_first: str | None = None
    name_middle: str | None = None
    party_key: str | None = None

    def last_key(self) -> str | None:
        if self.name_last:
            return norm_name_token(self.name_last)
        parsed = parse_subject_name(self.raw_name)
        return norm_name_token(parsed[0])

    def first_key(self) -> str | None:
        if self.name_first:
            return norm_name_token(self.name_first)
        parsed = parse_subject_name(self.raw_name)
        return norm_name_token(parsed[1])


@dataclass
class NamePair:
    query_id: str
    subject_name: str
    party_raw_name: str
    party_name_last: str | None
    party_name_first: str | None
    party_name_middle: str | None
    label: int
    label_kind: str
    label_source: str
    party_role: str = "defendant"
    source_party_key: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LabelInventory:
    n_total: int = 0
    n_human: int = 0
    n_suggestion: int = 0
    n_other: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def records_from_mappings(rows: Iterable[Mapping[str, Any]]) -> list[NameRecord]:
    out: list[NameRecord] = []
    for row in rows:
        raw = " ".join(str(row.get("raw_name") or "").split())
        if not raw:
            continue
        last = row.get("name_last")
        first = row.get("name_first")
        middle = row.get("name_middle")
        out.append(
            NameRecord(
                raw_name=raw,
                name_last=(str(last).strip() if last else None) or None,
                name_first=(str(first).strip() if first else None) or None,
                name_middle=(str(middle).strip() if middle else None) or None,
                party_key=(str(row["party_key"]) if row.get("party_key") else None),
            )
        )
    return out


def synthetic_fixture_records() -> list[NameRecord]:
    return records_from_mappings(SYNTHETIC_FIXTURE_NAMES)


def _comma_space_variant(record: NameRecord) -> str | None:
    raw = record.raw_name
    last, first, middle = parse_subject_name(raw)
    if not last or not first:
        return None
    given = first if not middle else f"{first} {middle}"
    if "," in raw:
        variant = f"{given} {last}"
    else:
        variant = f"{last}, {given}"
    collapsed = " ".join(variant.split())
    if collapsed.upper() == raw.upper():
        return None
    return collapsed


def _drop_middle_variant(record: NameRecord) -> str | None:
    last, first, middle = parse_subject_name(record.raw_name)
    if not last or not first or not middle:
        return None
    if "," in record.raw_name:
        variant = f"{last}, {first}"
    else:
        variant = f"{first} {last}"
    collapsed = " ".join(variant.split())
    if collapsed.upper() == record.raw_name.upper():
        return None
    return collapsed


def _case_variant(record: NameRecord) -> str:
    return record.raw_name.title()


def build_synthetic_pairs(
    names: Sequence[NameRecord],
    *,
    seed: int = 7,
    max_hard_negatives_per_query: int = 1,
) -> list[NamePair]:
    """Pair-level labels only. Does not emit court case / charge rows."""
    if not names:
        return []
    rng = random.Random(seed)
    indexed = list(enumerate(names))
    by_last: dict[str, list[tuple[int, NameRecord]]] = {}
    for i, rec in indexed:
        key = rec.last_key()
        if key:
            by_last.setdefault(key, []).append((i, rec))
    pairs: list[NamePair] = []
    for qi, subject in indexed:
        query_id = f"q{qi:05d}"
        pairs.append(
            NamePair(
                query_id=query_id,
                subject_name=subject.raw_name,
                party_raw_name=subject.raw_name,
                party_name_last=subject.name_last,
                party_name_first=subject.name_first,
                party_name_middle=subject.name_middle,
                label=1,
                label_kind=LABEL_SYNTHETIC_EXACT_POSITIVE,
                label_source=LABEL_SOURCE_SYNTHETIC,
                source_party_key=subject.party_key,
            )
        )
        for variant in (
            _comma_space_variant(subject),
            _drop_middle_variant(subject),
            _case_variant(subject),
        ):
            if not variant or variant == subject.raw_name:
                continue
            v_last, v_first, v_middle = parse_subject_name(variant)
            pairs.append(
                NamePair(
                    query_id=query_id,
                    subject_name=subject.raw_name,
                    party_raw_name=variant,
                    party_name_last=v_last,
                    party_name_first=v_first,
                    party_name_middle=v_middle,
                    label=1,
                    label_kind=LABEL_SYNTHETIC_NEAR_POSITIVE,
                    label_source=LABEL_SOURCE_SYNTHETIC,
                    source_party_key=None,
                )
            )
        last_key = subject.last_key()
        first_key = subject.first_key()
        near_pool = [
            rec
            for _j, rec in by_last.get(last_key or "", [])
            if rec.raw_name != subject.raw_name
            and rec.first_key()
            and rec.first_key() != first_key
        ]
        if near_pool:
            near = rng.choice(near_pool)
            pairs.append(
                NamePair(
                    query_id=query_id,
                    subject_name=subject.raw_name,
                    party_raw_name=near.raw_name,
                    party_name_last=near.name_last,
                    party_name_first=near.name_first,
                    party_name_middle=near.name_middle,
                    label=0,
                    label_kind=LABEL_SYNTHETIC_NEAR_DUP_NEGATIVE,
                    label_source=LABEL_SOURCE_SYNTHETIC,
                    source_party_key=near.party_key,
                )
            )
        hard_pool = [rec for _j, rec in indexed if rec.last_key() and rec.last_key() != last_key]
        if hard_pool:
            for _ in range(max_hard_negatives_per_query):
                hard = rng.choice(hard_pool)
                pairs.append(
                    NamePair(
                        query_id=query_id,
                        subject_name=subject.raw_name,
                        party_raw_name=hard.raw_name,
                        party_name_last=hard.name_last,
                        party_name_first=hard.name_first,
                        party_name_middle=hard.name_middle,
                        label=0,
                        label_kind=LABEL_SYNTHETIC_HARD_NEGATIVE,
                        label_source=LABEL_SOURCE_SYNTHETIC,
                        source_party_key=hard.party_key,
                    )
                )
    return pairs


def _human_gt_from_band_or_label(row: Mapping[str, Any]) -> tuple[int, str] | None:
    """Map a human row to (0/1, kind) or None if leave_in_review / not GT.

    Gold eval labels win when present. Otherwise MATCH_REVIEW band:
      auto → link, no-link → reject, review → leave_in_review (exclude).
    Suggestions must already have been filtered out by the caller.
    """
    eval_label = str(row.get("label") or "").strip().lower()
    band = str(row.get("confidence_band") or "").strip().lower()
    if eval_label == LABEL_LEAVE_IN_REVIEW or (not eval_label and band == "review"):
        return None
    if eval_label == LABEL_REJECT or band == "no-link":
        return 0, LABEL_HUMAN_REJECT
    if eval_label == LABEL_LINK or band == "auto":
        return 1, LABEL_HUMAN_LINK
    return None


def pairs_from_human_decisions(rows: Iterable[Mapping[str, Any]]) -> list[NamePair]:
    """Only `review_status=human` rows. Suggestions are rejected as labels.

    `leave_in_review` (human band `review`) is not GT and is dropped.
    """
    pairs: list[NamePair] = []
    for i, row in enumerate(rows):
        status = str(row.get("review_status") or "")
        actor = str(row.get("actor") or "")
        if status == REVIEW_STATUS_SUGGESTION or actor == "system:suggestion":
            continue
        if status and status != REVIEW_STATUS_HUMAN:
            continue
        subject_name = " ".join(str(row.get("subject_name") or "").split())
        party_name = " ".join(
            str(row.get("party_raw_name") or row.get("raw_name") or "").split()
        )
        if not subject_name or not party_name:
            continue
        mapped = _human_gt_from_band_or_label(row)
        if mapped is None:
            continue
        label, kind = mapped
        pairs.append(
            NamePair(
                query_id=f"human-{row.get('subject_ref') or i}",
                subject_name=subject_name,
                party_raw_name=party_name,
                party_name_last=row.get("party_name_last") or row.get("name_last"),
                party_name_first=row.get("party_name_first") or row.get("name_first"),
                party_name_middle=row.get("party_name_middle") or row.get("name_middle"),
                label=label,
                label_kind=kind,
                label_source=LABEL_SOURCE_HUMAN,
                source_party_key=str(row["party_key"]) if row.get("party_key") else None,
            )
        )
    return pairs


def count_leave_in_review(rows: Iterable[Mapping[str, Any]]) -> int:
    n = 0
    for row in rows:
        status = str(row.get("review_status") or "")
        actor = str(row.get("actor") or "")
        if status == REVIEW_STATUS_SUGGESTION or actor == "system:suggestion":
            continue
        label = str(row.get("label") or "").strip().lower()
        band = str(row.get("confidence_band") or "").strip().lower()
        if label == LABEL_LEAVE_IN_REVIEW or (not label and band == "review"):
            n += 1
    return n


def inventory_from_counts(rows: Iterable[Mapping[str, Any]]) -> LabelInventory:
    n_human = n_suggestion = n_other = n_total = 0
    for row in rows:
        n = int(row.get("n") or 0)
        n_total += n
        status = str(row.get("review_status") or "")
        actor = str(row.get("actor") or "")
        if status == REVIEW_STATUS_HUMAN:
            n_human += n
        elif status == REVIEW_STATUS_SUGGESTION or actor == "system:suggestion":
            n_suggestion += n
        else:
            n_other += n
    return LabelInventory(
        n_total=n_total,
        n_human=n_human,
        n_suggestion=n_suggestion,
        n_other=n_other,
    )


def split_query_ids(
    pairs: Sequence[NamePair],
    *,
    seed: int = 7,
    test_frac: float = 0.3,
) -> tuple[list[str], list[str]]:
    qids = sorted({p.query_id for p in pairs})
    rng = random.Random(seed)
    rng.shuffle(qids)
    if len(qids) < 2:
        return qids, qids
    n_test = max(1, int(round(len(qids) * test_frac)))
    n_test = min(n_test, len(qids) - 1)
    test = qids[:n_test]
    train = qids[n_test:]
    return train, test


def filter_pairs(pairs: Sequence[NamePair], query_ids: Sequence[str]) -> list[NamePair]:
    allowed = set(query_ids)
    return [p for p in pairs if p.query_id in allowed]


def pair_dicts(pairs: Sequence[NamePair]) -> list[dict[str, Any]]:
    return [p.as_dict() for p in pairs]


def summarize_pairs(pairs: Sequence[NamePair]) -> dict[str, int]:
    counts: dict[str, int] = {
        "n_pairs": len(pairs),
        "n_positive": sum(1 for p in pairs if p.label == 1),
        "n_negative": sum(1 for p in pairs if p.label == 0),
        "n_queries": len({p.query_id for p in pairs}),
        "n_human_pair_labels": sum(
            1 for p in pairs if p.label_source == LABEL_SOURCE_HUMAN
        ),
    }
    for p in pairs:
        key = f"n_kind_{p.label_kind}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _host_from_env() -> str:
    host = (
        os.environ.get("DATABRICKS_HOST")
        or os.environ.get("DATABRICKS_WORKSPACE_URL")
        or ""
    ).strip()
    if host and not host.startswith("http"):
        host = "https://" + host
    return host.rstrip("/")


def _token_from_env() -> str:
    return (
        os.environ.get("DATABRICKS_TOKEN")
        or os.environ.get("DATABRICKS_ACCESS_TOKEN")
        or ""
    ).strip()


def warehouse_query(
    sql: str,
    *,
    warehouse_id: str,
    host: str | None = None,
    token: str | None = None,
    wait_timeout_s: int = 50,
) -> list[dict[str, Any]]:
    """Run a SQL warehouse statement via REST. Returns column-aligned dicts.

    Names stay in memory for the training process. Callers must not write
    live PII into git or MLflow artifacts.
    """
    host = (host or _host_from_env()).rstrip("/")
    token = token or _token_from_env()
    if not host or not token or not warehouse_id:
        raise RuntimeError(
            "SQL warehouse pull needs DATABRICKS_HOST, DATABRICKS_TOKEN, "
            "and a warehouse id"
        )
    payload = json.dumps(
        {
            "warehouse_id": warehouse_id,
            "statement": sql,
            "wait_timeout": f"{int(wait_timeout_s)}s",
            "disposition": "INLINE",
            "format": "JSON_ARRAY",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        urljoin(host + "/", "api/2.0/sql/statements"),
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=wait_timeout_s + 20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    status = (body.get("status") or {}).get("state") or body.get("state")
    statement_id = body.get("statement_id")
    deadline = time.time() + 180
    while status in {"PENDING", "RUNNING"} and time.time() < deadline:
        time.sleep(2)
        poll = urllib.request.Request(
            urljoin(host + "/", f"api/2.0/sql/statements/{statement_id}"),
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urllib.request.urlopen(poll, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        status = (body.get("status") or {}).get("state") or body.get("state")
    if status != "SUCCEEDED":
        raise RuntimeError(f"warehouse statement did not succeed: {status}")
    manifest = body.get("manifest") or {}
    cols = [c.get("name") for c in (manifest.get("schema") or {}).get("columns") or []]
    data_array = ((body.get("result") or {}).get("data_array")) or []
    rows: list[dict[str, Any]] = []
    for raw in data_array:
        rows.append({cols[i]: raw[i] if i < len(raw) else None for i in range(len(cols))})
    return rows


def spark_query(spark: Any, sql: str) -> list[dict[str, Any]]:
    return [row.asDict(recursive=True) for row in spark.sql(sql).collect()]


def load_sf_party_names(
    *,
    spark: Any | None = None,
    warehouse_id: str | None = None,
    limit: int | None = None,
) -> list[NameRecord]:
    sql = SF_PARTY_NAME_SQL
    if limit is not None:
        sql = sql + f" LIMIT {int(limit)}"
    if spark is not None:
        rows = spark_query(spark, sql)
    elif warehouse_id:
        rows = warehouse_query(sql, warehouse_id=warehouse_id)
    else:
        raise RuntimeError("load_sf_party_names needs spark or warehouse_id")
    records = records_from_mappings(rows)
    if limit is not None:
        return records[: int(limit)]
    return records


def load_label_inventory(
    *,
    spark: Any | None = None,
    warehouse_id: str | None = None,
) -> LabelInventory:
    try:
        if spark is not None:
            rows = spark_query(spark, LABEL_INVENTORY_SQL)
        elif warehouse_id:
            rows = warehouse_query(LABEL_INVENTORY_SQL, warehouse_id=warehouse_id)
        else:
            return LabelInventory()
    except Exception as exc:  # noqa: BLE001 — inventory is optional
        print("name_match: match_decision inventory skipped:", exc)
        return LabelInventory()
    return inventory_from_counts(rows)


def load_human_pairs(
    *,
    spark: Any | None = None,
    warehouse_id: str | None = None,
) -> list[NamePair]:
    try:
        if spark is not None:
            rows = spark_query(spark, HUMAN_LABEL_SQL)
        elif warehouse_id:
            rows = warehouse_query(HUMAN_LABEL_SQL, warehouse_id=warehouse_id)
        else:
            return []
    except Exception as exc:  # noqa: BLE001
        print("name_match: human label pull skipped:", exc)
        return []
    return pairs_from_human_decisions(rows)


def load_eval_table_rows(
    *,
    spark: Any | None = None,
    warehouse_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load gold.name_match_eval. Missing table → empty list (honest N=0)."""
    try:
        if spark is not None:
            return spark_query(spark, EVAL_TABLE_SQL)
        if warehouse_id:
            return warehouse_query(EVAL_TABLE_SQL, warehouse_id=warehouse_id)
    except Exception as exc:  # noqa: BLE001 — empty eval is honest
        print("name_match: gold.name_match_eval missing or unreadable:", exc)
        print("name_match: treating n_human=0 (not synthesizing GT)")
        return []
    print("name_match: no spark/warehouse for eval table; n_human=0 (not synthesizing)")
    return []
