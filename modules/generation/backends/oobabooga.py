from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, Dict, Any
from modules.core.config import BaseConfig
from modules.generation.backend_patterns import Backend, BackendConfig
from modules.generation.generation_patterns import GenerationConfig

import httpx  # Using httpx for async HTTP requests
import asyncio
import logging
import time
import json
import os

# Initialize console logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Load environment variables, if any are used
from dotenv import load_dotenv
load_dotenv()

FAKE_OUTPUT = False

OOBABOOGA_URL = "http://127.0.0.1:5000/v1/chat/completions"

# Updated function for custom streaming chat with the Oobabooga API
async def async_custom_streaming_chat(query: str, config_dict: dict, chat_history: list):
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

    # Extract only the keys that are valid for the Oobabooga API
    mode = config_dict.get("mode", "chat")
    config_dict["mode"] = mode  # in case we had to set to a default
    valid_keys = [
        "frequency_penalty", "max_tokens", "presence_penalty", "stop",
        "temperature", "top_k", "top_p", "context"
    ]
    if mode == "chat":
        valid_keys += ["character", "chat_template_str", "user_name", "bot_name", "greeting"]
        if "character" not in config_dict:  # required for chat mode, could set a default somewhere though
            config_dict["character"] = "Assistant"
    elif mode == "instruct":
        valid_keys += ["instruction_template", "instruction_template_str"]
    filtered_config = {k: v for k, v in config_dict.items() if k in valid_keys}
    # Format the chat history for the Oobabooga API
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

    data = {
        "messages": formatted_chat_history,
        **filtered_config,
        "stream": True  # Ensure streaming is enabled
    }

    # print(f"TEST - data: {data}")

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
            # print(f"TIMESTAMP: {time.time()}")
            async with httpx.AsyncClient() as client:  # apparently shouldn't be inside the generator?
                # response = await client.post(
                #     OOBABOOGA_URL,  # Oobabooga API endpoint
                #     json=data,
                #     headers={"Content-Type": "application/json"},
                #     timeout=None  # Disable timeout for streaming responses
                # )

                complete_response = ""
                # print(f"TIMESTAMP: {time.time()}")
                async with client.stream(
                    method="POST",
                    url=OOBABOOGA_URL,  # Oobabooga API endpoint
                    json=data,
                    headers={"Content-Type": "application/json"},
                    timeout=None  # Disable timeout for streaming responses
                ) as response:
                    # print(f"TIMESTAMP: {time.time()}")
                    async for line in response.aiter_lines():
                        # print(f"TIMESTAMP: {time.time()}")
                        if line.startswith('data:'):
                            json_data = line[len('data:'):].strip()  # Extract the JSON string
                            payload = json.loads(json_data)  # Parse the JSON string into a Python dictionary
                            if 'choices' in payload and len(payload['choices']) > 0:
                                message = payload['choices'][0].get('message', {})
                                content = message.get('content', '')  # Safely get the content
                                complete_response += content
                                partial_response = {
                                    "message_chunk": content,
                                    "complete_message": None,
                                    "id": payload.get("id"),
                                    "created": time.time(),
                                    # "created": payload.get("created"),
                                    "model": payload.get("model"),
                                    "finish_reason": payload.get("choices")[0].get("finish_reason")
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
            "id": payload.get("id"),
            "created": payload.get("created"),
            "model": payload.get("model"),
            "finish_reason": payload.get("choices")[0].get("finish_reason")
        }
    
    logger.debug("Yielding final response.")
    yield final_response


class OobaboogaBackendConfig(BackendConfig):
    """
    Configuration class for the Oobabooga backend. Inherits from BackendConfig.
    Inherits from BaseConfig and defines specific fields relevant to LLM Backend.
    Do NOT use any attributes whose names start with "model_" or it will cause errors
    """

    name_of_model: str  # This might not be used depending on the Oobabooga API setup
    backend_model_settings: dict

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for OobaboogaBackendConfig."""
        return "./config/schemas/generation/backends/oobabooga.yml"

class OobaboogaBackend(Backend):
    """
    Oobabooga-specific Backend implementation.

    Attributes:
        backend_config (BackendConfig): Configuration specific to Oobabooga.
    """

    def __init__(self, backend_config: BackendConfig):
        """
        Initializes the OobaboogaBackend with specific backend configuration.

        Args:
            backend_config (BackendConfig): The configuration for the Oobabooga backend.
        """
        super().__init__(backend_config=backend_config)  # Call to the base class initializer

    async def generate_response(self, prompt: str, chat_history: list, generation_config: GenerationConfig, prefix: str = None) -> str:
        """
        Generates a response from Oobabooga based on the given prompt and generation configuration.

        TODO: Refactor out the output logic to a separate function so it's not CLI-specific.

        Args:
            prompt (str): The prompt to send to Oobabooga.
            chat_history (list): Previous chat history to provide as context.
            generation_config (GenerationConfig): Configuration for generation parameters.
            prefix (str): The prefix to print before the response.

        Returns:
            str: The response generated by Oobabooga.
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