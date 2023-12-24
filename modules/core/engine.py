
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Type, TypeVar, Optional, Union, Any, List, Dict, get_args, get_origin
from datetime import datetime
import os
import copy
import yaml

from modules.core.config import BaseConfig
from modules.core.patterns import Config, State
from modules.generation.llm_patterns import LLMConfig
from modules.generation.llm_manager import LLMManager
from modules.text_processing.transformation_patterns import TransformationConfig
from modules.text_processing.transformation_manager import TransformationManager  
from modules.text_processing.parsing_patterns import ParsingConfig
from modules.text_processing.parsing_manager import ParsingManager
from modules.interfaces.patterns import Interface, INTERFACE_CLASSES
from modules.utils import save_yaml, save_json, load_yaml, load_json

# All possible interface classes must be imported here
from modules.interfaces.patterns import Interface
from modules.interfaces.cli import CLIInterface
from modules.interfaces.webui import WebInterface

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
        interface (Interface): Interface for the conversation/game.
        transformation_manager (TransformationManager): Manager for text transformations.
        parsing_manager (ParsingManager): Manager for parsing input text.
        output_path (str): Path to the output file where the conversation/game state should be saved.
    """
    app_name: Optional[str] = None
    config_class: Type[Config] = Config
    state_class: Type[State] = State
    config: Config
    state: State
    interface: Interface
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
        interface_class = globals()[INTERFACE_CLASSES[self.config.interface_type]]
        self.interface = interface_class(self.config.interface_config)
        self.llm_manager = LLMManager(self.config.llm_config)
        self.transformation_manager = TransformationManager(self.config.transformation_config)
        self.parsing_manager = ParsingManager(self.config.parsing_config)
        # Other managers go here potentially


    def run(self):
        """
        Manages the interactive chat session.
        """
        chat_history = []
    
        # FOR REFERENCE, THE OLD LOGIC:

    # ## Chat loop
    # while True:
    #     try:
    #         query = input_provider("\n\nYou: ")
    #         if query is None:
    #             resp = input("Do you want to cancel and replace the last query? (yes/no): ")
    #             if resp.lower() == 'yes':
    #                 chat_history = chat_history[:-2] if len(chat_history) >= 2 else []
    #                 display_chat_history(chat_history)
    #                 continue
    #             else:
    #                 # In case of 'no' or any other input, just continue to get new input.
    #                 continue

    #         if transformations:
    #             query = transform_input(query, transformations)

    #         os.system('cls' if os.name == 'nt' else 'clear')
    #         display_chat_history(chat_history)
    #         print(f"\n\nYou: {query}\n")
    #         print("")

    #         timestamp = datetime.utcnow().isoformat() + 'Z'
    #         user_message = {
    #             "role": "user", 
    #             "content": query, 
    #             "timestamp": timestamp,
    #             "num_tokens": count_tokens(query),
    #             "truncated": False
    #         }
    #         chat_history.append(user_message)
    #         chat_history = truncate_chat_history(chat_history, context_limit, max_tokens)

    #         history_items = [
    #             item for item in chat_history
    #             if not item.get('truncated', False) or item.get('protected', False)
    #         ]

    #         chat_coroutine = custom_streaming_chat(api_key, query, config_dict, history_items, logger)
    #         complete_response = ""
    #         ai_prefix = config.ai_prefix

    #         first_message = True

    #         try:
    #             async for chunk in chat_coroutine:
    #                 if isinstance(chunk, dict):
    #                     if "error" in chunk:
    #                         print(f"\nError: {chunk['error']}\n")
    #                         chat_history = chat_history[:-1]  # Remove the last user message
    #                         break  # Exit this try block to re-prompt the user
    #                     else:
    #                         complete_response = chunk.get("complete_message", "")
    #                 else:
    #                     if first_message:
    #                         print(f"{ai_prefix}", end="", flush=True)
    #                         first_message = False
    #                     print(f"{chunk}", end="", flush=True)
    #         except KeyboardInterrupt:
    #             print("Your query has been canceled. You may enter a new one.")
    #             logger.info("User query canceled.")
    #             continue

    #         if "error" not in chunk:
    #             timestamp = datetime.utcnow().isoformat() + 'Z'
    #             new_response = {
    #                 "role": "assistant",
    #                 "content": complete_response,
    #                 "timestamp": timestamp,
    #                 "num_tokens": count_tokens(complete_response),
    #                 "truncated": False
    #             }
    #             chat_history.append(new_response)
    #             chat_history = truncate_chat_history(chat_history, context_limit, max_tokens)

    #             with open(output_filepath, 'w') as f:
    #                 output_data = {
    #                     "conversation": chat_history,
    #                     "configuration": config_dict,
    #                     "input": input_filepath
    #                 }
    #                 output_data["configuration"].pop("default_input", None)
    #                 json.dump(output_data, f, indent=4)

    #     except KeyboardInterrupt:
    #         logger.info("User forced exit. Exiting program.")
    #         print("Exiting program.")
    #         break

        while True:
            try:

                ## TODO: find a way to move this logic to the interface,
                ## because for GUI users it doesn't make sense to couple 
                ## blank input with something that should be a button press instead.
                user_input = self.interface.read_input("\n\nYou: ")
                if user_input == "":
                    user_decision = self.interface.read_input("Cancel last query? (yes/no): ")
                    if user_decision.lower() == 'yes':
                        if len(self.state.chat_history) >= 2:
                            self.state.chat_history = self.state.chat_history[:-2]
                        self.interface.display_chat_history(self.state.chat_history)
                        continue
                    else:
                        continue  # Continue to get new input in case of 'no' or other input

                llm_prompt = self.generate_prompt(user_input)
                self.add_message_to_history("user", llm_prompt)
                os.system('cls' if os.name == 'nt' else 'clear')
                self.interface.display_chat_history(self.state.chat_history)

                llm_output = self.llm_manager.generate_response(llm_prompt, chat_history, prefix=None)

                # Insert post-processing, error checking, etc.

                self.add_message_to_history("assistant", llm_output)


                self.truncate_chat_history()

            except KeyboardInterrupt:
                logger.info("User forced exit. Exiting program.")
                break

        if self.output_path:
            if self.output_path.endswith(".json"):
                self.save_json(self.output_path)
            elif self.output_path.endswith(".yml"):
                self.save_yaml(self.output_path)
            else:
                raise ValueError(f"Invalid output file type: {self.output_path}. Valid values are .json and .yml")

    def generate_prompt(self, user_input: str) -> str:
        return user_input
    
    def add_message_to_history(self, role: str, content: str, timestamp: str = None, num_tokens: int = None, truncated: bool = False):
        """
        Adds a message to the chat history.

        Args:
            role (str): The role of the message sender ('user' or 'assistant').
            content (str): The content of the message.
            timestamp (str, optional): Timestamp of the message. Defaults to current UTC time if not provided.
            num_tokens (int, optional): Number of tokens in the message. Calculated if not provided.
            truncated (bool, optional): Indicates if the message is truncated. Defaults to False.
        """
        if not timestamp:
            timestamp = datetime.utcnow().isoformat() + 'Z'
        if num_tokens is None:
            num_tokens = self.llm_manager.count_tokens(content)

        self.state.chat_history.append({
            "role": role,
            "content": content,
            "timestamp": timestamp,
            "num_tokens": num_tokens,
            "truncated": truncated
        })


    def truncate_chat_history(self) -> None:
        """
        Truncate chat history based on token limits.

        Parameters:
        - chat_history (list): Chat interactions to potentially truncate.
        - context_limit (int): The maximum number of tokens allowed in the chat context.
        - max_tokens (int): The maximum number of tokens for the assistant's response.

        Returns:
        - list: Potentially truncated chat history.
        """
        # Pull needed data from config files
        context_limit = self.config.llm_config.backend_config.model_settings.get("context_limit", None)
        if context_limit is None:
            raise ValueError("Context limit not specified in model config.")
        max_tokens = self.config.llm_config.generation_config.max_tokens
        chat_history = self.state.chat_history
        
        # Calculate the total tokens for all messages.
        current_tokens = sum([item['num_tokens'] for item in chat_history])
        # print(f"Tokens in chat history so far: {current_tokens}")
        max_input_tokens = context_limit - max_tokens
        # print(f"Input tokens limit: {max_input_tokens}")

        if current_tokens <= max_input_tokens:
            # print(f"Tokens in chat history so far: {current_tokens}")
            # If the total tokens are already within limits, no need to truncate further.
            for item in chat_history:
                item['truncated'] = False
            return chat_history

        # Start from the oldest message to decide which to truncate.
        for item in chat_history[1:]:
            # print(f"Tokens in chat history so far: {current_tokens}")
            if not item.get('protected', False):
                current_tokens -= item['num_tokens']
                item['truncated'] = True
                if current_tokens <= max_input_tokens:
                    break

        # No output needed, we modified chat_history in-place


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

