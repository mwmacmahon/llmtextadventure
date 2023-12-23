
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type, Dict, Any
from modules.core.config import BaseConfig
from modules.generation.backend_patterns import Backend, BackendConfig
from modules.generation.generation_patterns import GenerationConfig

import openai
import asyncio
import logging
import tiktoken
import os

# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
openai.util.logger.setLevel(logging.WARNING)

# Load OpenAI API key from .env file
from dotenv import load_dotenv
load_dotenv()

# # doesn't work, the call is wrong or something
# def count_tokens_openai_api(text: str) -> int:
#     """
#     Count the number of tokens in a text string using OpenAI API.

#     Args:
#         text (str): The text string to count tokens for.

#     Returns:
#         int: The number of tokens in the text.
#     """
#     return len(openai.Completion.create(prompt=text, max_tokens=0)["usage"]["total_tokens"])

def count_tokens_tiktoken(text: str, encoding_name: str = "cl100k_base") -> int:
    """
    Count the number of tokens in a text string using tiktoken.

    Args:
        text (str): The text string to count tokens for.
        encoding_name (str): The encoding name to use with tiktoken.

    Returns:
        int: The number of tokens in the text.
    """
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(text))

def count_tokens(text: str) -> int:
    """
    Count the number of tokens in a text string.

    Args:
        text (str): The text string to count tokens for.

    Returns:
        int: The number of tokens in the text.
    """
    # return count_tokens_openai_api(text)
    return count_tokens_tiktoken(text)

def custom_streaming_chat(query: str, config_dict: dict, chat_history: list):
    """
    Initiate a custom streaming chat with OpenAI GPT models and yield real-time responses.

    Args:
        api_key (str): The API key for OpenAI.
        query (str): The user query to send to the chat model.
        config_dict (dict): Configuration dictionary containing parameters like model name, max tokens, etc.
        chat_history (list): Previous chat history to provide as context.
        logger (logging.Logger): Logger object to log messages.

    Yields:
        str/dict: Yields model's real-time responses in chunks and the final response as a dictionary.
    """
    logger.debug("Initiating custom streaming chat.")
    api_key = os.environ.get("OPENAI_API_KEY", None)
    if api_key:
        openai.api_key = api_key
    else:
        logger.error("No OpenAI API key found in environment variables.")
        raise ValueError("No OpenAI API key found in environment variables.")

    # Extract only the keys that are valid for the OpenAI API
    valid_keys = ['model', 'max_tokens', 'temperature', 'top_p', 'n', 'stop', 'presence_penalty', 'frequency_penalty']
    filtered_config = {k: config_dict[k] for k in valid_keys if k in config_dict}

    
    # Format the chat history for OpenAI API
    formatted_chat_history = [
        {
            "role": msg["role"], 
            "content": msg["content"]
        } 
        for msg in chat_history if not msg.get('truncated', False) or msg.get('protected', False)
    ]
    formatted_chat_history.append(
        {
            "role": "user",
            "content": query
        }
    )
    
    try:
        response = openai.ChatCompletion.create(
            messages=formatted_chat_history,
            stream=True,
            **filtered_config
        )
    except Exception as e:
        # logger.error(f"API call failed: {e}")  # log in main script
        yield {"error": str(e)}
        return

    complete_response = ""
    
    try:
        for chunk in response:
            delta = chunk.get("choices")[0].get("delta", {})
            content = delta.get("content", "")
            complete_response += content
            yield content
    except Exception as e:
        logger.error(f"API call failed: {e}")
        yield {"error": str(e)}
        return
    
    final_response = {
        "complete_message": complete_response,
        "id": chunk.get("id"),
        "created": chunk.get("created"),
        "model": chunk.get("model"),
        "finish_reason": chunk.get("choices")[0].get("finish_reason")
    }
    
    logger.debug("Yielding final response.")
    yield final_response

async def async_custom_streaming_chat(query: str, config_dict: dict, chat_history: list):
    """
    Initiate a custom streaming chat with OpenAI GPT models and yield real-time responses.

    Args:
        api_key (str): The API key for OpenAI.
        query (str): The user query to send to the chat model.
        config_dict (dict): Configuration dictionary containing parameters like model name, max tokens, etc.
        chat_history (list): Previous chat history to provide as context.
        logger (logging.Logger): Logger object to log messages.

    Yields:
        str/dict: Yields model's real-time responses in chunks and the final response as a dictionary.
    """
    logger.debug("Initiating custom streaming chat.")
    api_key = os.environ.get("OPENAI_API_KEY", None)
    if api_key:
        openai.api_key = api_key
    else:
        logger.error("No OpenAI API key found in environment variables.")
        raise ValueError("No OpenAI API key found in environment variables.")

    # Extract only the keys that are valid for the OpenAI API
    valid_keys = ['model', 'max_tokens', 'temperature', 'top_p', 'n', 'stop', 'presence_penalty', 'frequency_penalty']
    filtered_config = {k: config_dict[k] for k in valid_keys if k in config_dict}
    
    # Format the chat history for OpenAI API
    formatted_chat_history = [
        {
            "role": msg["role"], 
            "content": msg["content"]
        } 
        for msg in chat_history if not msg.get('truncated', False) or msg.get('protected', False)
    ]
    formatted_chat_history.append(
        {
            "role": "user",
            "content": query
        }
    )
    
    try:
        response = await openai.ChatCompletion.acreate(
            messages=formatted_chat_history,
            stream=True,
            **filtered_config
        )
    except Exception as e:
        # logger.error(f"API call failed: {e}")  # log in main script
        yield {"error": str(e)}
        return

    complete_response = ""
    
    try:
        async for chunk in response:
            delta = chunk.get("choices")[0].get("delta", {})
            content = delta.get("content", "")
            complete_response += content
            yield content
    except Exception as e:
        logger.error(f"API call failed: {e}")
        yield {"error": str(e)}
        return
    
    final_response = {
        "complete_message": complete_response,
        "id": chunk.get("id"),
        "created": chunk.get("created"),
        "model": chunk.get("model"),
        "finish_reason": chunk.get("choices")[0].get("finish_reason")
    }
    
    logger.debug("Yielding final response.")
    yield final_response


class OpenAIBackendConfig(BackendConfig):
    """
    Configuration class for the OpenAI backend. Inherits from BackendConfig.
    Inherits from BaseConfig and defines specific fields relevant to LLM Backend.
    Do NOT use any attributes whose names start with "model_" or it will cause errors
    """

    name_of_model: str
    openai_settings: dict

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for OpenAIBackendConfig."""
        return "./config/schemas/generation/backends/openai.yml"


class OpenAIBackend(Backend):
    """
    OpenAI specific Backend implementation.

    Attributes:
        backend_config (BackendConfig): Configuration specific to OpenAI.
    """

    def __init__(self, backend_config: BackendConfig):
        """
        Initializes the OpenAIBackend with specific backend configuration.

        Args:
            backend_config (BackendConfig): The configuration for the OpenAI backend.
        """
        super().__init__(backend_config=backend_config)  # Call to the base class initializer

    def generate_response(self, prompt: str, chat_history: list, generation_config: GenerationConfig, prefix: str = None) -> str:
        """
        Generates a response from OpenAI based on the given prompt and generation configuration.

        TODO: Refactor out the output logic to a separate function so it's not CLI-specific.

        Args:
            prompt (str): The prompt to send to OpenAI.
            chat_history (list): Previous chat history to provide as context.
            generation_config (GenerationConfig): Configuration for generation parameters.
            prefix (str): The prefix to print before the response.

        Returns:
            str: The response generated by OpenAI.
        """
        params_dict = generation_config.model_dump()  # Guaranteed to have all the required params
        history_items = [item for item in chat_history if not item.get('truncated', False) or item.get('protected', False)]
        complete_response = ""
        first_message = True


        params_dict["model"] = self.backend_config.name_of_model
        params_dict["context_limit"] = self.backend_config.openai_settings["context_limit"]
        
        try:
            # chat_coroutine = async_custom_streaming_chat(prompt, params_dict, history_items)
            # async for chunk in chat_coroutine:
            chat_coroutine = custom_streaming_chat(prompt, params_dict, history_items)
            for chunk in chat_coroutine:
                if isinstance(chunk, dict):
                    if "error" in chunk:
                        print(f"\nError: {chunk['error']}\n")
                        break  # Exit this try block to re-prompt the user
                    else:
                        complete_response = chunk.get("complete_message", "")
                else:
                    if first_message:
                        if prefix:
                            print(f"{prefix}", end="", flush=True)
                        first_message = False
                    print(f"{chunk}", end="", flush=True)
        except KeyboardInterrupt:
            print("Your query has been canceled. You may enter a new one.")
            logger.info("User query canceled.")

        return complete_response