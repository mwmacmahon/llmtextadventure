import logging

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Union, Any, Callable, Type


# Initialize console logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



def cleanup_whitespace(text: str, state_dict: dict = {}) -> str:
    """
    Clean up consecutive whitespaces in the input text.

    Args:
        text (str): The original input text.

    Returns:
        str: Input text with cleaned up whitespace.
    """
    # print("Calling cleanup_whitespace()")
    return ' '.join(text.split())

def prepend_prefix(text: str, state_dict: dict = {}, prefix: str = "") -> str:
    """
    Prepend a given prefix to the input text.

    Args:
        text (str): The original input text.
        prefix (str): The prefix to be prepended.

    Returns:
        str: Input text with the prefix prepended.
    """
    # print("Calling prepend_prefix()")
    return prefix + text

def append_suffix(text: str, state_dict: dict = {}, suffix: str = "") -> str:
    """
    Append a given suffix to the input text.

    Args:
        text (str): The original input text.
        suffix (str): The suffix to be appended.

    Returns:
        str: Input text with the suffix appended.
    """
    # print("Calling append_suffix()")
    return text + suffix
