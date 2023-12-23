
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Type, TypeVar, Optional, Union, Any, Dict, get_args, get_origin
from modules.core.config import BaseConfig
from modules.core.patterns import Config, State
from modules.generation.llm_patterns import LLMConfig
from modules.generation.llm_manager import LLMEngine
from modules.text_processing.transformation_patterns import TransformationConfig
from modules.text_processing.transformation_manager import TransformationManager  
from modules.text_processing.parsing_patterns import ParsingConfig
from modules.text_processing.parsing_manager import ParsingManager

class ConversationEngine(BaseModel):
    """
    ConversationEngine controls the flow and logic of the conversation or game, 
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

    config_class: Type[Config] = Config
    state_class: Type[State] = State
    llm_engine: LLMEngine
    config: Config
    state: State
    transformation_manager: TransformationManager
    parsing_manager: ParsingManager
    # Other managers as needed


    def __init__(self, 
            llm_engine: LLMEngine,  # Pass in the existing LLMEngine instance
            config: Optional[State]=None, 
            state: Optional[State]=None
        ):
        """
        Initializes the ConversationEngine with necessary components and configuration.

        app_state is only passed in in ConversationEngine subclasses.

        Args:
            llm_engine (LLMEngine): Engine for interfacing with the LLM.
            config (Config, optional): Full configuration/state for the conversation/game.
            state (State, optional): Optional state from an existing conversation.
        """
        self.llm_engine = llm_engine
        self.config = config if config is not None else self.config_class.create()
        self.state = state if state is not None else self.state_class.create()
        self.transformation_manager = TransformationManager(self.config.transformation_config)
        self.parsing_manager = ParsingManager(self.config.parsing_config)
        # Other managers go here potentially

    def process_text(self, text):
        """
        Processes the given text as part of the conversation or game logic.

        Args:
            text (str): Text to be processed.

        Returns:
            str: Processed text or response.
        """
        # TODO: implement this logic 
        pass


