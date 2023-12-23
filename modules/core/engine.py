
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Type, TypeVar, Optional, Union, Any, Dict, get_args, get_origin
from modules.core.config import BaseConfig
from modules.core.patterns import Config, State
from modules.generation.llm_patterns import LLMConfig
from modules.generation.llm_manager import LLMManager
from modules.text_processing.transformation_patterns import TransformationConfig
from modules.text_processing.transformation_manager import TransformationManager  
from modules.text_processing.parsing_patterns import ParsingConfig
from modules.text_processing.parsing_manager import ParsingManager
from modules.utils import save_yaml, save_json, load_yaml, load_json
import os
import copy
import yaml

# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConversationEngine:
    """
    ConversationEngine controls the flow and logic of the conversation or game, 
    interfacing between the user and the LLM. It handles loading and updating the
    conversation or game state, interpreting user inputs, generating appropriate prompts 
    for the LLM and updating the state based on the user and LLM's outputs.
    It integrates with various managers to process input, manage state, and apply transformations.

    Subclass this for specific types of conversations or games.

    Does not use schema, as it is not a configuration class. Instead, the config_class
    and state_class attributes are used to determine the base classes and schemas for the 
    config and state attributes. As such, subclasses do not need to touch __init__().

    Attributes:
        config_class (Type[Config]): Default class for the configuration. Determines schema used.
        state_class (Type[State]): Default class for the state. Determines schema used.
        llm_manager (LLMManager): Engine for interfacing with the LLM.
        config (Config): Full configuration/state for the conversation/game.
        state (State) State of the conversation, such as message history, etc.
        transformation_manager (TransformationManager): Manager for text transformations.
        parsing_manager (ParsingManager): Manager for parsing input text.
        output_path (str): Path to the output file where the conversation/game state should be saved.
    """
    app_name: Optional[str] = None
    config_class: Type[Config] = Config
    state_class: Type[State] = State
    config: Config
    state: State
    llm_manager: LLMManager
    transformation_manager: TransformationManager
    parsing_manager: ParsingManager
    # Other managers as needed
    output_path: Optional[str] = None

    def __init__(self, app_name: str = None, config_data: dict = {}, state_data: dict = {}, output_path: str = None):
        """
        Initializes the ConversationEngine with necessary components and configuration.

        app_state is only passed in in ConversationEngine subclasses.

        Args:
            config_data (dict, optional): Full or partial nested Config-equivalent dict.
            state_data (dict, optional): Full or partial nested State-equivalent dict.
        """
        # Register app_name if provided
        if app_name:
            self.app_name = app_name

        # Register output_file if provided
        if output_path:
            if output_path.endswith(".json") or output_path.endswith(".yml"):
                self.output_path = output_path
            else:
                raise ValueError(f"Invalid output file type: {output_path}. Valid values are .json and .yml")

        # Deep copy the data to avoid modifying the original
        config_data = copy.deepcopy(config_data)
        state_data = copy.deepcopy(state_data)

        # Dynamically instantiate Config and State objects, then the Managers
        self.config = self.config_class.create(config_data)
        self.state = self.state_class.create(state_data)
        self.llm_manager = LLMManager(self.config.llm_config)
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
        chat_history = []
        prefix = "AI: "
        return self.llm_manager.generate_response(text, chat_history, prefix)

    def to_dict(self):
        """
        Recursively converts the configuration to a dictionary, including nested configurations.

        Returns:
            dict: Dictionary representing the configuration.
        """
        config_dict = self.config.to_dict()
        state_dict = self.state.to_dict()
        data = {"config": config_dict, "state": state_dict}
        if self.app_name:
            data["app_name"] = self.app_name
        return data
    
    def print_yaml(self):
        """
        Prints configuration and state to the console in YAML format.
        """
        yaml_string = yaml.dump(self.to_dict(), default_flow_style=False)
        print(yaml_string)

    def save_yaml(self, file_path: str):
        """
        Saves configuration and state to a single file in YAML format.

        Args:
            file_path (str): The file path where the YAML should be saved.
        """
        save_yaml(self.to_dict(), file_path)

    def save_json(self, file_path: str):
        """
        Saves configuration and state to a single file in JSON format.

        Args:
            file_path (str): The file path where the JSON should be saved.
        """
        save_json(self.to_dict(), file_path)

