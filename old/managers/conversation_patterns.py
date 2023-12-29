from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Type, TypeVar, Optional, Union, Any, Dict, get_args, get_origin
from modules.core.config import BaseConfig
from modules.generation.llm_patterns import LLMConfig
from modules.generation.llm_manager import LLMEngine
from modules.text_processing.transformation_patterns import TransformationConfig
from modules.text_processing.transformation_manager import TransformationManager  
from modules.text_processing.parsing_patterns import ParsingConfig
from modules.text_processing.parsing_manager import ParsingManager

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
    conversations, e.g. the ones orchestrated via ChatManager (as opposed to a ConversationManager).
    Inherits from BaseConfig and defines specific fields shared by all conversations,
    mostly related to the message history.
    Subclassed versions may add many additional fields, for example for tracking game state.
    Do NOT use any attributes whose names start with "model_" or it will cause errors

    Attributes:
        history (list): List of messages in the conversation/game,
        llm_io_history (list): List of raw messages with no post-processing
    """

    history: list
    llm_io_history: list

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for State."""
        return "./config/schemas/state.yml"


# Protocol to suggest that a class is a Backend.
# This is used to type hint ____Backend classes in the LLMEngine.
class Backend(Protocol):
class IConversationManager({BaseModel}):
    """
    ConversationManager controls the flow and logic of the conversation or game, 
    interfacing between the user and the LLM. It handles loading and updating the
    conversation or game state, interpreting user inputs, generating appropriate prompts 
    for the LLM and updating the state based on the user and LLM's outputs.
    It integrates with various managers to process input, manage state, and apply transformations.

    Does not use schema, as it is not a configuration class. Instead, the config_class
    and state_class attributes are used to determine the base classes and schemas for the 
    config and state attributes. As such, subclasses do not need to touch __init__().

    Attributes:
        config_class (Type[Config]): Default class for the configuration. Determines schema used.
        state_class (Type[State]): Default class for the state. Determines schema used.
        llm_engine (LLMEngine): Engine for interfacing with the LLM.
        config (Config): Full configuration/state for the conversation/game.
        state (State) State of the conversation, such as message history, etc.
        transformation_manager (TransformationManager): Manager for text transformations.
        parsing_manager (ParsingManager): Manager for parsing input text.
    """