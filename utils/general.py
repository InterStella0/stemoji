from __future__ import annotations

import contextvars
import inspect
import itertools
import logging
import re
import typing
from typing import AsyncGenerator

import discord
import starlight
from discord import app_commands
from discord.ext import commands

from core.typings import EContext, EInteraction

if typing.TYPE_CHECKING:
    from core.ui_components import PaginationContextView
else:
    PaginationContextView = discord.ui.View

emoji_context = contextvars.ContextVar("emoji_user_used")
slash_context = contextvars.ContextVar("ctx")
LOGGER_NAME = "stemoji"
SLASH_REGEX = re.compile("/(?P<slash>(?:\w{1,32}\s*)+):")


def slash_parse(text: str) -> str:
    try:
        context: EContext | EInteraction = slash_context.get()
    except LookupError:
        logging.getLogger(LOGGER_NAME).warning(f"No slash context found for {text}")
        return text

    bot = context.client if isinstance(context, EInteraction) else context.bot
    scope = getattr(context.guild, 'id', None)

    def mention_slash(matching):
        name = matching["slash"]
        app_id = bot.tree.get_command_named(name, scope)  # noqa: pycharm is doin dum
        return f"</{name}:{app_id or 0}>"

    return SLASH_REGEX.sub(mention_slash, text)


T = typing.TypeVar('T', bound=typing.Any)
V = typing.TypeVar('V', bound=PaginationContextView)


class PageItem(typing.Generic[T, V]):
    __slots__ = ('view', 'iteration', 'item', 'embed')

    def __init__(self, view: V, iteration: int,
                 item: starlight.InlinePaginationItem[typing.Sequence[T]], embed: discord.Embed) -> None:
        self.view: V = view
        self.iteration: int = iteration
        self.item: starlight.InlinePaginationItem[typing.Sequence[T]] = item
        self.embed: discord.Embed = embed

    def format(self, **kwargs: typing.Any) -> None:
        self.item.format(**kwargs)


async def iter_pagination(
        pagination_view: starlight.SimplePaginationView, context: EContext
) -> AsyncGenerator[tuple[int, starlight.InlinePaginationItem], None]:
    counter = itertools.count(0)
    async for item in starlight.inline_pagination(pagination_view, context):
        yield next(counter), item


async def inline_pages(
        items: list[T], ctx: EContext, per_page: int = 6, cls: type[V] = None,
        **kwargs
) -> AsyncGenerator[PageItem[T, V], None]:
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


# thx danny for this func :3
# error prone for future dpy version, rember!
resolve_annotation = discord.utils.resolve_annotation


I = typing.TypeVar('I')  # identity usage only!
MISSING = discord.utils.MISSING

def find_describe_converter(annotation) -> str | MISSING:
    from core.converter import DescribeConverter
    if (
        inspect.isclass(annotation) and issubclass(annotation, DescribeConverter)
    ) or isinstance(annotation, DescribeConverter):
        return annotation.__annotation_describe__
    return MISSING


def resolve_describe_converter(annotation) -> app_commands.locale_str | str | MISSING:
    if getattr(annotation, '__origin__', None) is typing.Union:
        for tp in annotation.__args__:
            # when union, only the first describe converter is used if not MISSING.
            desc = find_describe_converter(tp)
            if desc is not MISSING:
                return desc

    return find_describe_converter(annotation)


def describe(**params: app_commands.locale_str | str) -> typing.Callable[[I], I]:
    def inner(func: I) -> I:
        if isinstance(func, commands.Command):
            for name, param in func.clean_params.items():
                desc = resolve_describe_converter(param.annotation)
                if param.description is None:
                    if name in params:
                        desc = params[name]

                    if desc is not MISSING:
                        func.params[name] = param.replace(description=desc)
                else:
                    if name not in params and desc is not MISSING:
                        params[name] = desc
        elif isinstance(func, (app_commands.Command, app_commands.Group)):
            for name, param in func.parameters:
                desc = resolve_describe_converter(param.annotation)
                if name not in params and desc is not MISSING:
                    params[name] = desc
        else:
            signature = commands.core.Signature.from_callable(func)
            new_params = {}
            for name, param in signature.parameters.items():
                new_params[name] = param
                if name in params:
                    desc = params[param.name]
                elif param.description is not None:
                    desc = param.description
                else:
                    globalns = func.__globals__
                    annotation = resolve_annotation(param.annotation, globalns, globalns, {})
                    desc = resolve_describe_converter(annotation)

                if desc is MISSING:
                    continue

                new_params[name] = param.replace(description=desc)
                params[name] = desc

            func.__signature__ = signature.replace(parameters=new_params.values())

        return app_commands.describe(**params)(func)

    return inner
