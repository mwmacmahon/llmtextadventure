
from typing import Type, TypeVar, Optional, Union, List, Any, Dict, get_args, get_origin, get_type_hints, ClassVar
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
import yaml
import inspect
import importlib

from modules.interfaces.patterns import Interface, InterfaceConfig


class CLIInterfaceConfig(InterfaceConfig):
    """"""
    interface_mode: str

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for HFTGIBackendConfig."""
        return "./config/schemas/interfaces/cli.yml"


class CLIInterface(Interface):
    """
    CLI specific Interface implementation.

    Attributes:
        interface_config (InterfaceConfig): Configuration specific to CLI.
    """
    def __init__(self, interface_config):
        super().__init__(interface_config)

    def read_input(self, input_prompt: str = ""):
        return input(input_prompt)

    def write_output(self, message, output_prefix: str = ""):
        print(message)

    def display_chat_history(self, chat_history: List[Dict[str, str]]) -> None:
        """
        Render the chat history as if it occurred in real-time.

        Parameters:
        - chat_history (list): List of chat interactions.
        """
        for entry in chat_history:
            role = entry.get("role", "")
            content = entry.get("content", "")
            if role == "system":
                print(f"System: {content}\n")
            elif role == "user":
                print(f"You: {content}\n")
            elif role == "assistant":
                print(f"Assistant: {content}\n")
        