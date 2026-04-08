import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # pip install tomli (backport for <3.11)

import tomli_w
from pathlib import Path
from typing import TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def load_config(path: str | Path, model: type[T]) -> T:
    """Load a TOML config file and validate it against a Pydantic model.

    Args:
        path: Path to the .toml config file.
        model: Pydantic model class to validate against.

    Returns:
        A validated instance of the given model.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValidationError: If the config data does not match the model.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    return model(**data)


def save_config(path: str | Path, config: BaseModel) -> None:
    """Serialise a Pydantic model back to a TOML file.

    Args:
        path: Destination .toml path (will be overwritten).
        config: Validated Pydantic model instance.
    """
    path = Path(path)
    data = config.model_dump()
    with open(path, "wb") as f:
        tomli_w.dump(data, f)
