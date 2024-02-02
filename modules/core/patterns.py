from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Type, TypeVar, Optional, Union, Any, Dict, get_args, get_origin
from modules.core.config import BaseConfig
from modules.generation.llm_patterns import LLMConfig
from modules.generation.llm_manager import LLMManager
from modules.text_processing.transformation_patterns import TransformationConfig
from modules.interfaces.patterns import Interface, InterfaceConfig

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class Config(BaseConfig):
    """
    Top-level configuration class that covers all aspects of the conversation or game.
    This is the tree of configurations:
    - Config: Top-level configuration for the conversation/game.
        - interface_type: type of interface to instantiate - determines Interface/InterfaceConfig class
        - InterfaceConfig: Configuration for the interface.
        - LLMConfig: Configuration for the LLM.
            - BackendConfig: Configuration for the LLM backend.
        - TransformationConfig: Configuration for text transformations.
    """

    interface_type: str
    interface_config: InterfaceConfig
    llm_config: LLMConfig
    transformation_config: TransformationConfig

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        return "./config/schemas/config.yml"
    

class State(BaseConfig):
    """
    State class holding the state of the conversation/game. May be subclassed for specific
    types of conversations, but this one is designed to be used directly for general 
    conversations, e.g. the ones orchestrated via ChatManager (as opposed to a ConversationEngine).
    Inherits from BaseConfig and defines specific fields shared by all conversations,
    mostly related to the message history.
    Subclassed versions may add many additional fields, for example for tracking game state.
    Do NOT use any attributes whose names start with "model_" or it will cause errors

    Attributes:
        chat_history (list): List of messages in the conversation/game,
        llm_io_history (list): List of raw messages with no post-processing
    """

    chat_history: list
    llm_io_history: list

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for State."""
        return "./config/schemas/state.yml"
