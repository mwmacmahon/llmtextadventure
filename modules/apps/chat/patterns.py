
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type, Any, Dict
from modules.core.config import BaseConfig
from modules.core.patterns import Config, State

# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Contains the State, Config, and ConversationEngine classes for Sample Game A

class ChatConfig(Config):
    """
    Manages the static config of the game, adaptable to different scenarios.
    This is designed to cover the immutable but configurable settings of the app.
    This subclass is for the Chat app.

    Attributes:
        [Inherited from Config] interface_type, interface_config, llm_config, transformation_config, parsing_config
    """
    # [Inherited from Config] interface_type, interface_config, llm_config, transformation_config, parsing_config

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for Chat app's config."""
        return "./config/schemas/apps/chat/config.yml"
    

class ChatState(State):
    """
    Manages the state of the chat, from conversation history to current context.

    Attributes:
        [Inherited from State] history, llm_io_history
    """
    # [Inherited from State] history, llm_io_history

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for Chat app's state."""
        return "./config/schemas/apps/chat/default_state.yml"
    
