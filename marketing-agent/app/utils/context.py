import contextvars
from typing import Optional

# Global context variable to store the current session's output folder
current_output_folder: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_output_folder", default=None
)

def set_current_output_folder(folder: str):
    """Sets the current session's output folder."""
    current_output_folder.set(folder)

def get_current_output_folder() -> Optional[str]:
    """Retrieves the current session's output folder."""
    return current_output_folder.get()
