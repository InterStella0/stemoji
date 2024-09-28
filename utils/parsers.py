import os
import re
import typing

from starlight.utils.search import FuzzyFilter
from dotenv import load_dotenv

load_dotenv()

VALID_EMOJI_SEMI = re.compile(r";(?P<emoji_name>\w{1,31});")
UNPAIRED_SEMICOLON = re.compile(r";.*(?![^;]*;)")

VALID_EMOJI_NORMAL = re.compile(r":(?P<emoji_name>\w{1,31}):")
UNPAIRED_EMOJI = re.compile(r":.*(?![^:]*:)")

def find_latest_unpaired_semicolon(s: str) -> str | None:
    valid_pairs = VALID_EMOJI_SEMI.findall(s)
    for pair in valid_pairs:
        s = s.replace(pair, '|')

    last_invalid_semicolon = UNPAIRED_SEMICOLON.search(s)
    return last_invalid_semicolon.group() if last_invalid_semicolon else None

def find_latest_unpaired_emoji(s: str) -> str | None:
    valid_pairs = VALID_EMOJI_NORMAL.findall(s)
    for pair in valid_pairs:
        s = s.replace(pair, '|')

    last_invalid_semicolon = UNPAIRED_EMOJI.search(s)
    return last_invalid_semicolon.group() if last_invalid_semicolon else None


class FuzzyInsensitive(FuzzyFilter):
    def __init__(self, query: str, **kwargs):
        super().__init__(query.casefold(), **kwargs)

    def get_ratio(self, query: str, value: str) -> float:
        return super().get_ratio(query, value.casefold())


def environment_boolean(name: str, value: str) -> bool:
    if value.upper() in ("TRUE", "1"):
        return True
    elif value.upper() in ("FALSE", "0"):
        return False

    raise RuntimeError(f'{name}="{value}" IS NOT A VALID BOOLEAN CHOICE, MUST BE "TRUE" OR "FALSE"!')


T = typing.TypeVar('T')

@typing.overload
def env(name: str) -> str: ...

@typing.overload
def env(name: str, data_type: type[T]) -> T: ...

def env(name: str, data_type: type[T] = str) -> T:
    try:
        value = os.environ[name]
    except KeyError:
        raise RuntimeError(f'"{name}" is not set in the environment variable. It is required.')

    if data_type is bool:
        return environment_boolean(name, value)

    if value is data_type:
        return value
    return data_type(value)


TOKEN_REGEX = re.compile(r'[a-zA-Z0-9_-]{23,28}\.[a-zA-Z0-9_-]{6,7}\.[a-zA-Z0-9_-]{27,}')
