import json
import os
import yaml
from datetime import datetime
from modules.old.streamingapi import count_tokens

from pydantic import BaseModel
from typing import List, Optional, Dict, Union, Any

from modules.old.input_transformers import \
    INPUT_TRANSFORMERS, cast_to_transformer_obj, \
    InputTransformer, InputTransformerArgs
# , \
#     CleanupWhitespaceTransformer, CleanupWhitespaceArgs, \
#     PrependPrefixTransformer, PrependPrefixArgs, \
#     AppendSuffixTransformer, AppendSuffixArgs


class ChatConfig(BaseModel):
    model: str
    context_limit: int
    default_input: str
    ai_prefix: Optional[str] = "Assistant: "
    transformations: Optional[List[InputTransformer]] = []
    
    # OpenAI parameters with defaults
    max_tokens: Optional[int] = 100
    temperature: Optional[float] = 1
    top_p: Optional[float] = 1
    n: Optional[int] = 1
    stop: Optional[Union[str, None]] = None
    presence_penalty: Optional[float] = 0
    frequency_penalty: Optional[float] = 0

def get_filepath(
        args_value: str,
        prompt: str,
        default_value: str = None,
        extension: str = ".json",
        default_dirs: List[str] = ["profiles", "chat_histories"],
        is_input: bool = False
    ) -> str:
    """
    Retrieve the input filepath based on user input or default value.

    Parameters:
    - args_value (str): Command line argument for filename.
    - prompt (str): Prompt to ask user for filename.
    - default_value (str): Default filename if user provides none.
    - default_dirs (list): List of folders to check in order of priority for existing files.
                           For output files, last folder is assumed to be the default save 
                           location if the file doesn't already exist. Current working directory
                           is prepended to this list, i.e. it is always checked first.
    - extension (str): Expected file extension (default is .json).
    - is_input (bool): If False, skips the check to see if the file already exists.

    Returns:
    - str: Full filepath.
    """
    if args_value and not os.path.isabs(args_value):
        filename = args_value
    else:
        if default_value:
            prompt_with_default = f"{prompt} (default: {default_value}): "
        else:
            prompt_with_default = f"{prompt}: "
        filename = input(prompt_with_default) or default_value

    # Ensure the filename has the correct extension
    if not filename.endswith(extension):
        filename += extension

    # Check if the user provided an absolute filepath
    if os.path.isabs(filename):
        if os.path.exists(filename):
            return filename
        elif is_input:
            raise FileNotFoundError(f"File '{filename}' not found.")

    # Define potential file paths
    file_paths = [
        os.path.join(os.getcwd(), filename)
    ] + [
        os.path.join(os.getcwd(), folder, filename)
        for folder in default_dirs
    ]

    # Check for the file's existence in the specified paths
    for file_path in file_paths:
        if os.path.exists(file_path):
            return file_path
    if is_input:
        raise FileNotFoundError(f"File '{filename}' not found in any of the searched directories.")

    # if file doesn't exist, use the last folder as the default save location
    return file_paths[-1]


def display_chat_history(chat_history: List[Dict[str, str]]) -> None:
    """
    Render the chat history as if it occurred in real-time.

    Parameters:
    - chat_history (list): List of chat interactions.
    """
    for entry in chat_history:
        role = entry.get("role", "")
        content = entry.get("content", "")
        if role == "system":
            print(f"System: {content}\n")
        elif role == "user":
            print(f"You: {content}\n")
        elif role == "assistant":
            print(f"Assistant: {content}\n")

def truncate_chat_history(chat_history: List[Dict[str, str]], context_limit: int, max_tokens: int) -> List[Dict[str, str]]:
    """
    Truncate chat history based on token limits.

    Parameters:
    - chat_history (list): Chat interactions to potentially truncate.
    - context_limit (int): The maximum number of tokens allowed in the chat context.
    - max_tokens (int): The maximum number of tokens for the assistant's response.

    Returns:
    - list: Potentially truncated chat history.
    """
    
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

    return chat_history

def are_transformations_valid(transformations: List[Dict[str, Any]]) -> bool:
    available_names = [func.__name__ for func in INPUT_TRANSFORMERS]
    for transformation in transformations:
        if transformation['name'] not in available_names:
            return False
    return True

def load_config(file_path: str = "config.yml") -> dict:
    """Load YAML configuration."""
    with open(file_path, 'r') as stream:
        return yaml.safe_load(stream)
    
def load_chatconfig(data: dict) -> ChatConfig:
    return ChatConfig(**data)

# now we just combine the dicts
# def update_chatconfig(original: ChatConfig, update: ChatConfig) -> ChatConfig:
#     updated_data = original.model_dump()
#     updated_data.update(update.model_dump())
#     return ChatConfig(**updated_data)

def convert_to_config_obj(config_data: Union[Dict[str, Any], ChatConfig]) -> ChatConfig:
    """
    Convert the given configuration data to a ChatConfig object.

    Args:
        config_data (Union[Dict[str, Any], ChatConfig]): 
            A dictionary representation or a ChatConfig object.

    Returns:
        ChatConfig: The resulting ChatConfig object.
    """
    if isinstance(config_data, ChatConfig):
        return config_data
    else:
        config_data = config_data.copy()
        # Convert the transformations list if it exists
        if 'transformations' in config_data:
            config_data['transformations'] = [cast_to_transformer_obj(t) for t in config_data['transformations']]
        return ChatConfig(**config_data)


