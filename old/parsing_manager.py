
from typing import Type, TypeVar, Optional, Union, Any, Dict, get_args, get_origin
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from modules.core.config import BaseConfig
from modules.core.patterns import State
from modules.text_processing.parsing_patterns import ParsingConfig
from modules.text_processing.parsing_functions import \
    find_key_phrase

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

PARSING_FUNCTIONS = {
    'find_key_phrase': find_key_phrase
}

class ParsingManager:
    """
    ParsingManager handles the parsing of text using configured rules.
    It interprets and analyzes text for commands, flags, or special inputs.

    Attributes:
        parsing_config (ParsingConfig): Configuration for parsing rules.
    """

    parsing_config: ParsingConfig

    def __init__(self, parsing_config: ParsingConfig):
        """
        Initializes the ParsingManager with parsing configuration.

        Args:
            parsing_config (ParsingConfig): Configuration for parsing rules.
        """
        self.parsing_config = parsing_config

    def apply_single_parsing(self, parsing_name: str, text: str, state: Optional[State] = None, **kwargs) -> State:
        """
        Parses the text using a single parsing function.

        Args:
            parsing_name (str): Name of the parsing function to apply.
            text (str): Text to be parsed.
            state (Optional[State]): State of the conversation, passed to parsing functions.
            **kwargs: Additional arguments to be passed to the parsing function.

        Returns:
            State: Modified state of the conversation.
        """
        # print(f"Calling apply_single_parsing({parsing_name})")
        # Convert state to dict
        state_dict = state.model_dump() if state else {}
        # Get parsing function
        parsing_func = PARSING_FUNCTIONS.get(parsing_name)
        if parsing_func:
            new_state_dict = parsing_func(text, state_dict, **kwargs)
            return state.__class__.create(**new_state_dict)
        else:
            logger.warning(f"Parsing function '{parsing_name}' not found.")
            return state

    def apply_parsing_set(self, parsing_set: str, text: str, state: State = None, runtime_kwargs: dict = None) -> State:
        """
        Parses the text using a set of parsing functions defined in the configuration.

        Args:
            parsing_set (str): Name of the parsing set from the config file.
            text (str): Text to be parsed.
            state (Optional[State]): State of the conversation, passed to parsing functions.
            runtime_kwargs (Optional[dict]): Additional/overriding args to be passed to
                the parsing functions. Should be of form:
                {
                    'parsing_name': {
                        'arg_name': arg_value
                    }
                }
                It will apply to any parsing in the set that has the specified
                name, and will override any arguments specified in the ParsingConfig.

        Returns:
            State: Modified state of the conversation.
        """
        # print(f"Calling apply_parsing_set({parsing_set})")

        # Retrieve parsing list from configuration
        try:
            parsing_list = getattr(self.parsing_config, parsing_set)
        except AttributeError:
            logger.warning(f"Parsing set '{parsing_set}' not found.")
            return state
        
        # Apply each parsing function
        for parsing_dict in parsing_list:
            if parsing_dict['name'] in PARSING_FUNCTIONS:
                # Get args from config, then override with runtime args if they exist
                args = parsing_dict.get('args', {})
                if runtime_kwargs and parsing_dict['name'] in runtime_kwargs:
                    args.update(runtime_kwargs[parsing_dict['name']])
                state = self.apply_single_parsing(parsing_dict['name'], text, state, **args)
            else:
                logger.warning(f"Parsing function '{parsing_dict['name']}' not found.")



        return state