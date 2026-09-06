"""Condition-tree data model for the advanced search query builder.

This is the canonical definition of the tree shape the Python compiler
consumes. The TS side keeps a matching copy in src/lib/search.ts (the tree
model + URL codec the browser edits and forwards) — that file is now just the
client mirror of this contract; the original engine-side TS
(src/lib/search/types.ts, compileSearchQuery.ts) was retired when the search
engine moved fully to Python. Keep the two tree shapes in agreement.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal, Union

from pydantic import Field

from app.core.camel_model import CamelModel

Combinator = Literal["AND", "OR"]
FieldType = Literal["text", "enum", "number", "date", "boolean", "array"]

Operator = Literal[
    "contains", "not_contains", "equals", "starts_with",             # text
    "is_any_of", "is_none_of",                                       # enum
    "gt", "gte", "lt", "lte", "between",                             # number
    "before", "after", "on", "date_between",                         # date
    "is_true", "is_false",                                           # boolean
    "array_contains_any", "array_contains_all", "array_contains_none",  # array
    "is_empty", "is_not_empty",                                      # universal, gated by field.nullable
]


class ConditionValue(CamelModel):
    text: str | None = None
    values: list[str] | None = None
    number: float | None = None
    number_range: tuple[float, float] | None = None
    date: str | None = None  # "yyyy-mm-dd"
    date_range: tuple[str, str] | None = None


class Condition(CamelModel):
    id: str
    kind: Literal["condition"] = "condition"
    field: str  # key into that domain's field registry
    operator: Operator
    value: ConditionValue


class ConditionGroup(CamelModel):
    id: str
    kind: Literal["group"] = "group"
    combinator: Combinator
    children: list["ConditionNode"]


ConditionNode = Annotated[Union[Condition, ConditionGroup], Field(discriminator="kind")]

ConditionGroup.model_rebuild()

SearchDomain = Literal["attacks", "systems", "evaluation_activities", "countermeasures"]

SEARCH_DOMAINS: tuple[SearchDomain, ...] = (
    "attacks",
    "systems",
    "evaluation_activities",
    "countermeasures",
)


def is_search_domain(value: str) -> bool:
    return value in SEARCH_DOMAINS


SEARCH_DOMAIN_LABELS: dict[SearchDomain, str] = {
    "attacks": "Attacks / Vulnerabilities",
    "systems": "Systems",
    "evaluation_activities": "Evaluation Activities",
    "countermeasures": "Countermeasures",
}

# Hard caps to bound worst-case generated-SQL size, recursive-render depth, and
# shareable-URL length. Enforced both proactively in the TS UI and authoritatively
# here — see compile.py.
MAX_CONDITIONS = 25  # total leaf conditions across the whole tree
MAX_DEPTH = 5        # nested group levels, root = depth 1


def gen_id() -> str:
    return str(uuid.uuid4())


def empty_group(combinator: Combinator = "AND") -> ConditionGroup:
    return ConditionGroup(id=gen_id(), combinator=combinator, children=[])


def empty_condition() -> Condition:
    return Condition(id=gen_id(), field="", operator="contains", value=ConditionValue())


def count_leaves(node: Condition | ConditionGroup) -> int:
    if node.kind == "condition":
        return 1
    return sum(count_leaves(c) for c in node.children)


# Measures group nesting only — a leaf condition contributes 0, so a flat root
# group containing only conditions (no nested subgroups) has depth 1, and each
# level of group-within-group adds 1.
def get_depth(node: Condition | ConditionGroup) -> int:
    if node.kind == "condition":
        return 0
    if len(node.children) == 0:
        return 1
    return 1 + max((get_depth(c) for c in node.children), default=0)
