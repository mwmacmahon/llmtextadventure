
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type, Dict, Any
from modules.core.config import BaseConfig
from modules.generation.backend_patterns import Backend, BackendConfig
from modules.generation.generation_patterns import GenerationConfig

import openai
import asyncio
import logging
import tiktoken
import time
import os

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
openai.util.logger.setLevel(logging.WARNING)

# Load OpenAI API key from .env file
from dotenv import load_dotenv
load_dotenv()

FAKE_OUTPUT = False

def custom_streaming_chat(query: str, config_dict: dict, chat_history: list):
    """
    Initiate a custom streaming chat with OpenAI GPT models and yield real-time responses.

    Args:
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
    except KeyboardInterrupt:
        raise
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
            partial_response = {
                "message_chunk": content,
                "complete_message": None,
                "id": chunk.get("id"),
                "created": chunk.get("created"),
                "model": chunk.get("model"),
                "finish_reason": chunk.get("choices")[0].get("finish_reason")
            }
            yield partial_response  # Yield content as it arrives
    except KeyboardInterrupt:
        raise
    except Exception as e:
        logger.error(f"API call failed: {e}")
        yield {"error": str(e)}
        return
    
    final_response = {
        "message_chunk": None,
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

    if FAKE_OUTPUT:
        try:
            for i in range(100):
                await asyncio.sleep(0.2)
                partial_response = {
                    "message_chunk": "test",
                    "complete_message": None,
                    "id": "test",
                    "created": time.time(),
                    # "created": payload.get("created"),
                    "model": "test",
                    "finish_reason":"test"
                }
                yield partial_response  # Yield content as it arrives

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            raise
        
        final_response = {
            "message_chunk": None,
            "complete_message": "testest",
            "id": "test",
            "created": time.time(),
            # "created": payload.get("created"),
            "model": "test",
            "finish_reason":"test"
        }
    
    else:

        try:
            response = await openai.ChatCompletion.acreate(
                messages=formatted_chat_history,
                stream=True,
                **filtered_config
            )
            complete_response = ""
            async for chunk in response:
                delta = chunk.get("choices")[0].get("delta", {})
                content = delta.get("content", "")
                complete_response += content
                partial_response = {
                    "message_chunk": content,
                    "complete_message": None,
                    "id": chunk.get("id"),
                    "created": chunk.get("created"),
                    "model": chunk.get("model"),
                    "finish_reason": chunk.get("choices")[0].get("finish_reason")
                }
                yield partial_response  # Yield content as it arrives
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            raise
    
    final_response = {
        "message_chunk": None,
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
    backend_model_settings: dict

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for OpenAIBackendConfig."""
        return "./config/schemas/generation/backends/openai.yml"


class OpenAIBackend(Backend):
    """
    OpenAI-specific Backend implementation.

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

    async def generate_response(self, prompt: str, chat_history: list, generation_config: GenerationConfig, prefix: str = None) -> str:
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
        params_dict["context_limit"] = self.backend_config.backend_model_settings["context_limit"]
        
        try:
            # chat_coroutine = custom_streaming_chat(prompt, params_dict, history_items)
            # for chunk in chat_coroutine:
            chat_coroutine = async_custom_streaming_chat(prompt, params_dict, history_items)
            async for chunk in chat_coroutine:
                if "error" in chunk:
                    print(f"\nError: {chunk['error']}\n")
                    break  # Exit this try block to re-prompt the user
                elif chunk.get("complete_message", None):
                    complete_response = chunk.get("complete_message", "")
                elif chunk.get("message_chunk", None):
                    message_chunk = chunk.get("message_chunk", "")
                    if first_message:
                        if prefix:
                            print(f"{prefix}", end="", flush=True)
                        first_message = False
                    print(f"{message_chunk}", end="", flush=True)
        except KeyboardInterrupt:
            print("Your query has been canceled. You may enter a new one.")
            logger.info("User query canceled.")

        return complete_response