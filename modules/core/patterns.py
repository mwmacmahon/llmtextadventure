from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Type, TypeVar, Optional, Union, Any, Dict, get_args, get_origin
from modules.core.config import BaseConfig
from modules.generation.llm_patterns import LLMConfig
from modules.generation.llm_manager import LLMManager
from modules.text_processing.transformation_patterns import TransformationConfig
from modules.text_processing.transformation_manager import TransformationManager  
from modules.text_processing.parsing_patterns import ParsingConfig
from modules.text_processing.parsing_manager import ParsingManager

# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Config(BaseConfig):
    """
    Top-level configuration class that covers all aspects of the conversation or game.
    This is the tree of configurations:
    - Config: Top-level configuration for the conversation/game.
        - LLMConfig: Configuration for the LLM.
            - BackendConfig: Configuration for the LLM backend.
        - TransformationConfig: Configuration for text transformations.
        - ParsingConfig: Configuration for text parsing functions.
    """

    llm_config: LLMConfig
    transformation_config: TransformationConfig
    parsing_config: ParsingConfig

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
        history (list): List of messages in the conversation/game,
        raw_history (list): List of raw messages with no post-processing
    """

    history: list
    raw_history: list

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for State."""
        return "./config/schemas/state.yml"
