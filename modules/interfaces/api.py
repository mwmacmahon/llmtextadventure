
from typing import Type, TypeVar, Optional, Union, List, Any, Dict, get_args, get_origin, get_type_hints, ClassVar
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
import yaml
import inspect
import importlib

from modules.interfaces.patterns import Interface, InterfaceConfig
# from modules.core.engine import ConversationEngine

# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEngine = TypeVar('TEngine', bound='ConversationEngine')

class APIInterfaceConfig(InterfaceConfig):
    """"""
    interface_mode: str

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for HFTGIBackendConfig."""
        return "./config/schemas/interfaces/cli.yml"


class APIInterface(Interface):
    """
    API specific Interface implementation.

    Attributes:
        interface_config (InterfaceConfig): Configuration specific to API.
    """
    def __init__(self, interface_config):
        super().__init__(interface_config)

    def run_async(self, engine: TEngine):
        """
        Doesn't need to do anything, since if we are using the API interface,
        the engine's methods will be called via API and the main loop will
        occur on the client side.

        Args:
            engine (ConversationEngine): The engine managing the conversation logic.
        """
        pass

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
        