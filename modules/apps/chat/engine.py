
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type
from modules.core.config import BaseConfig
from modules.apps.chat.patterns import ChatConfig, ChatState
from modules.core.engine import ConversationEngine
from modules.core.patterns import Config, State


# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
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


    # # From parsing manager, for reference only
    # runtime_kwargs (Optional[dict]): Additional/overriding args to be passed to
    #     the parsing functions. Should be of form:
    #     {
    #         'parsing_name': {
    #             'arg_name': arg_value
    #         }
    #     }
    #     It will apply to any parsing in the set that has the specified
    #     name, and will override any arguments specified in the ParsingConfig.


    # async def process_user_input(self, user_input: str) -> Tuple[State, str]:
    #     """
    #     Process the user input, parsing and transforming it based on the Config
    #     and updating the current state based as dictated by the parsing functions.

    #     This function may be overridden in subclasses to add additional processing,
    #     such as by overriding kwargs in the parsing and transformation sets.
    #     """
    #     extra_parsing_args = {}  # Just to remind that this can be done in subclasses
    #     new_state = self.parsing_manager.apply_parsing_set(
    #         "user_input_parsings", user_input, self.state, extra_parsing_args
    #     )

    #     extra_transform_args = {}
    #     transformed_input = self.transformation_manager.apply_transformation_set(
    #         "user_input_transformations", user_input, new_state, extra_transform_args
    #     )

    #     return new_state, transformed_input


    # async def process_llm_output(self, llm_output: str, user_input: str) -> Tuple[State, str]:
    #     """
    #     Process the LLM output, parsing and transforming it based on the Config
    #     and updating the current state based as dictated by the parsing functions.
    #     The user input is also provided in case it is needed for additional
    #     logic in the subclasses.

    #     This function may be overridden in subclasses to add additional processing,
    #     such as by overriding kwargs in the parsing and transformation sets.
    #     """
    #     extra_parsing_args = {}  # Just to remind that this can be done in subclasses
    #     new_state = self.parsing_manager.apply_parsing_set(
    #         "llm_output_parsings", llm_output, self.state, extra_parsing_args
    #     )

    #     extra_transform_args = {}
    #     transformed_output = self.transformation_manager.apply_transformation_set(
    #         "llm_output_transformations", llm_output, new_state, extra_transform_args
    #     )

    #     return new_state, transformed_output

    # async def generate_llm_prompt(self, user_input: str) -> str:
    #     """
    #     Given the user input, assemble the prompt to send to the LLM.

    #     Will be overridden in subclasses.
    #     """
    #     return user_input
    
    # async def generate_response(self, llm_output: str, user_input: str) -> str:
    #     """
    #     Given the llm response and user input, assemble the final
    #     message sent back to the user. May use the self.state.___
    #     in order to display information about the conversation
    #     in subclasses.
        
    #     Will likely be overridden in subclasses.
    #     """
    #     return llm_output
    