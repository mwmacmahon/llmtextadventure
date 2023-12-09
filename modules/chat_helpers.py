import json
import os
import yaml
from datetime import datetime
from llmtextadventure.modules.streamingapi import count_tokens

from pydantic import BaseModel
from typing import List, Optional, Dict, Union, Any

from llmtextadventure.modules.input_transformers import \
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

def get_filepath(args_value: str, prompt: str, default_value: str = None, extension: str = ".json") -> str:
    """
    Retrieve the filepath based on user input or default value.

    Parameters:
    - args_value (str): Command line argument for filename.
    - prompt (str): Prompt to ask user for filename.
    - default_value (str): Default filename if user provides none.
    - extension (str): Expected file extension (default is .json).

    Returns:
    - str: Full filepath.
    """
    if args_value:
        filename = args_value
    else:
        filename = input(prompt) or default_value

    # Ensure the filename has the correct extension
    if not filename.endswith(extension):
        filename += extension

    # Define potential file paths
    current_dir_path = os.path.join(os.getcwd(), filename)
    profiles_dir_path = os.path.join(os.getcwd(), "profiles", filename)
    chat_histories_dir_path = os.path.join(os.getcwd(), "chat_histories", filename)

    # Check for the file's existence in the specified paths
    if os.path.exists(current_dir_path):
        return current_dir_path
    elif os.path.exists(profiles_dir_path):
        return profiles_dir_path
    elif os.path.exists(chat_histories_dir_path):
        return chat_histories_dir_path
    else:
        raise FileNotFoundError(f"File '{filename}' not found in any of the searched directories.")


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


