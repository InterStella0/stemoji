from __future__ import annotations
import contextvars
import itertools
import typing
from typing import AsyncGenerator

import discord
import starlight

from core.typings import EContext

if typing.TYPE_CHECKING:
    from core.ui_components import PaginationContextView

emoji_context = contextvars.ContextVar("emoji_user_used")

class PageItem:
    __slots__ = ('view', 'iteration', 'item', 'embed')

    def __init__(self, view: PaginationContextView, iteration: int, item: starlight.InlinePaginationItem, embed: discord.Embed) -> None:
        self.view = view
        self.iteration = iteration
        self.item = item
        self.embed = embed

async def iter_pagination(
        pagination_view: starlight.SimplePaginationView, context: EContext
) -> AsyncGenerator[tuple[int, starlight.InlinePaginationItem], None]:
    counter = itertools.count(0)
    async for item in starlight.inline_pagination(pagination_view, context):
        yield next(counter), item

T = typing.TypeVar('T')
async def inline_pages(
        items: list[T], ctx: EContext, per_page: int = 6, cls: type[PaginationContextView] = None,
        **kwargs
) -> AsyncGenerator[PageItem, None]:
    chunks = [*discord.utils.as_chunks(items, per_page)]
    page_size = len(chunks)
    if cls is None:
        from core.ui_components import PaginationContextView
        cls = PaginationContextView

    view = cls(chunks, **kwargs)
    async for i, item in iter_pagination(view, ctx):
        embed = discord.Embed()
        embed.set_footer(text=f"Page {view.current_page + 1}/{page_size}")
        yield PageItem(view, i, item, embed)

        if not item._future.done():
            item.format(embed=embed)
