from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base for any model that crosses the JSON boundary to/from Next.js.

    Internal attributes stay idiomatic Python snake_case; JSON in/out uses
    camelCase to match the existing TS API contract byte-for-byte (the
    frontend already consumes `vulnerabilityId`, `shortDescription`, etc.,
    and Phase 1.5/2.5 parity fixtures are camelCase JSON dumped straight
    from the TS engines) — `populate_by_name` lets code construct instances
    with snake_case kwargs while `model_dump(by_alias=True)` emits camelCase.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
