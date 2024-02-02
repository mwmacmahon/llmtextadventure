
## TODO: needs to be updated to match samplegame_a's engine class

from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Type, TypeVar, Optional, Union, Tuple, Any, List, Dict, get_args, get_origin
from datetime import datetime
import os
import copy
import yaml
import asyncio

from modules.core.config import BaseConfig
from modules.core.patterns import Config, State
from modules.generation.llm_patterns import LLMConfig
from modules.generation.llm_manager import LLMManager
from modules.text_processing.transformation_patterns import TransformationConfig
from modules.text_processing.transformation_manager import TransformationManager  
from modules.utils import save_yaml, save_json, load_yaml, load_json

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
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
        transformation_manager (TransformationManager): Manager for routine text transformations.
        output_path (str): Path to the output file where the conversation/game state should be saved.
    """
    app_name: Optional[str] = None
    config_class: Type[Config] = Config
    state_class: Type[State] = State
    config: Config
    state: State
    llm_manager: LLMManager
    transformation_manager: TransformationManager
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
        # Other managers go here potentially


    async def query(self, user_input: str):
        """
        Processes the user input, generates the LLM prompt, and updates the conversation history.

        Args:
            user_input (str): The user input text.

        Yields:
            Partial or complete responses from the LLM.
        """
        # Process user input and update state
        self.state, processed_user_input = await self.process_user_input(user_input)
        self.state, user_flag_response = await self.handle_user_flags()
        # Check for user flags and update state

        if processed_user_input is None:
            # No actual input to send to the LLM,
            # so just return the output from processing
            # the user flags
            yield {
                "status": "finished",  # signals that the response is complete
                "message": user_flag_response
            }
        else:
            # Yield the user response but still send
            # the remaining user input to the LLM
            yield {
                "status": "running",  # signals more response data is coming
                "message": user_flag_response
            }

        # Create LLM prompt, then send to LLM and get response
        llm_prompt = await self.generate_llm_prompt(processed_user_input)
        llm_output = await self.llm_manager.generate_response(llm_prompt, self.state.llm_io_history, prefix=None)

        # Process LLM output and generate response
        llm_output_text = llm_output  # this might not be true in the future, so making this explicit
        self.state, processed_llm_output =  await self.process_llm_output(llm_output_text, processed_user_input)
        response =  await self.generate_response(processed_llm_output, processed_user_input)

        # Add both user input and output to chat history
        await self.add_message_to_history("user", user_input, llm_prompt)
        await self.add_message_to_history("assistant", response, llm_output_text)

        # Truncate the chat history as needed
        await self.truncate_chat_history()

        # Save to output file if specified
        if self.output_path:
            if self.output_path.endswith(".json"):
                await self.save_json(self.output_path)
            elif self.output_path.endswith(".yml"):
                await self.save_yaml(self.output_path)
            else:
                raise ValueError(f"Invalid output file type: {self.output_path}. Valid values are .json and .yml")

        # Return a message signaling the response and processing is complete
        yield {
            "status": "finished",
            "message": llm_output
        }


    async def process_user_input(self, user_input: str) -> Tuple[State, str]:
        """
        Process the user input, parsing and transforming it based on the Config
        and updating the current state based as dictated by the parsing functions.

        This function may be overridden in subclasses to add additional processing,
        such as by overriding kwargs in the parsing and transformation sets.
        """

        new_state = self.state.model_copy(deep=True)

        extra_transform_args = {}
        transformed_input = self.transformation_manager.apply_transformation_set(
            "user_input_transformations", user_input, new_state, extra_transform_args
        )

        return new_state, transformed_input


    async def process_llm_output(self, llm_output: str, user_input: str) -> Tuple[State, str]:
        """
        Process the LLM output, parsing and transforming it based on the Config
        and updating the current state based as dictated by the parsing functions.
        The user input is also provided in case it is needed for additional
        logic in the subclasses.

        This function may be overridden in subclasses to add additional processing,
        such as by overriding kwargs in the parsing and transformation sets.
        """
        new_state = self.state.model_copy(deep=True)

        # Insert updates of state here based on parsing, if needed
        
        extra_transform_args = {}
        transformed_output = self.transformation_manager.apply_transformation_set(
            "llm_output_transformations", llm_output, new_state, extra_transform_args
        )

        return new_state, transformed_output


    async def handle_user_flags(self) -> Tuple[State, Optional[str]]:
        """
        Process the situational flags, updating the state and generating a response
        to the user based on the flags. Returns None for a response if
        no actionable flags are found.

        If it returns None for the response, the ConversationManager should
        not send anything to the LLM, but instead ask the user for more input.

        Will be overridden in subclasses.
        """
        # Copy the current state for modifications
        new_state = self.state.model_copy(deep=True)

        # If flags found, update state and generate response
        if False:
            return new_state, user_flags_response
        else:
            return new_state, None  # No flags found, return None for response

    async def generate_llm_prompt(self, user_input: str) -> str:
        """
        Given the user input, assemble the prompt to send to the LLM.

        Will be overridden in subclasses.
        """
        return user_input
    
    async def generate_response(self, llm_output: str, user_input: str) -> str:
        """
        Given the llm response and user input, assemble the final
        message sent back to the user. May use the self.state.___
        in order to display information about the conversation
        in subclasses.
        
        Will likely be overridden in subclasses.
        """
        return llm_output
    
    
    async def add_message_to_history(self, role: str, content: str, llm_io_content: str, timestamp: str = None, num_tokens: int = None, truncated: bool = False):
        """
        Adds a message to the chat history.

        Args:
            role (str): The role of the message sender ('user' or 'assistant').
            content (str): The user-visible content of the message.
            llm_io_content (str): The actual, final content of the message sent to or received from LLM.
            timestamp (str, optional): Timestamp of the message. Defaults to current UTC time if not provided.
            num_tokens (int, optional): Number of tokens in the message. Calculated if not provided.
            truncated (bool, optional): Indicates if the message is truncated. Defaults to False.
        """
        if not timestamp:
            timestamp = datetime.utcnow().isoformat() + 'Z'
        if num_tokens is None:
            num_tokens = await self.llm_manager.count_tokens(content)

        self.state.chat_history.append({
            "role": role,
            "content": content,
            "timestamp": timestamp,
            "num_tokens": num_tokens,
            "truncated": truncated
        })
        self.state.llm_io_history.append({
            "role": role,
            "content": llm_io_content,
            "timestamp": timestamp,
            "num_tokens": num_tokens,
            "truncated": truncated
        })


    async def truncate_chat_history(self) -> None:
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
        context_limit = self.config.llm_config.backend_config.backend_model_settings.get("context_limit", None)
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
    
    async def print_yaml(self):
        """
        Prints configuration and state to the console in YAML format.
        """
        yaml_string = await asyncio.to_thread(
            yaml.dump,
            self.to_dict(), 
            default_flow_style=False
        )
        print(yaml_string)

    async def save_yaml(self, file_path: str):
        """
        Saves configuration and state to a single file in YAML format.

        Args:
            file_path (str): The file path where the YAML should be saved.
        """
        await asyncio.to_thread(save_yaml,self.to_dict(), file_path)

    async def save_json(self, file_path: str):
        """
        Saves configuration and state to a single file in JSON format.

        Args:
            file_path (str): The file path where the JSON should be saved.
        """
        await asyncio.to_thread(save_json,self.to_dict(), file_path)


