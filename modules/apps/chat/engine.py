
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type
from modules.core.config import BaseConfig
from modules.apps.chat.patterns import ChatConfig, ChatState
from modules.core.engine import ConversationEngine
from modules.core.patterns import Config, State

# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChatEngine(ConversationEngine):
    """
    Controls the flow and logic of the conversation/game, interfacing between the user 
    and the LLM. It handles loading and updating the conversation/game state, interpreting 
    user inputs, generating appropriate prompts for the LLM and updating the state based 
    on the user and LLM's outputs. It integrates with various managers to process input, 
    manage state, and apply transformations.

    Does not use schema, as it is not a configuration class. Instead, the config_class
    and state_class attributes are used to determine the base classes and schemas for the 
    config and state attributes. As such, subclasses do not need to touch __init__().

    Attributes:
        [Inherited from ConversationEngine] config, state, llm_manager, transformation_manager, parsing_manager
        config_class (Type[Config]): Default class for the configuration 
        state_class (Type[State]): Default class for the state
    """
    # [Inherited from ConversationEngine] config, state, llm_manager, transformation_manager, parsing_manager
    config_class: Type[Config] = ChatConfig
    state_class: Type[State] = ChatState

    ## Init kept from base class - will use the config and state classes defined above
    ## and as such will use the schemas referenced in those classes

    # # Use base class for now
    # def process_text(self, text):
    #     """
    #     Processes the given text as part of the conversation or game logic.

    #     Args:
    #         text (str): Text to be processed.

    #     Returns:
    #         str: Processed text or response.
    #     """
    #     pass
