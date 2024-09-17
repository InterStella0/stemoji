import collections
import contextvars
import itertools
from typing import AsyncGenerator

import starlight

from core.typings import EContext

emoji_context = contextvars.ContextVar("emoji_user_used")

async def iter_pagination(
        pagination_view: starlight.SimplePaginationView, context: EContext
) -> AsyncGenerator[tuple[int, starlight.InlinePaginationItem], None]:
    counter = itertools.count(0)
    async for item in starlight.inline_pagination(pagination_view, context):
        yield next(counter), item
