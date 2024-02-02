import asyncio
import os
import json
import logging
import argparse
from datetime import datetime
from pydantic import BaseModel, Field, ValidationError
from pydantic.json import pydantic_encoder
from typing import Optional
from dotenv import load_dotenv
import yaml

from modules.old.streamingapi import custom_streaming_chat, count_tokens
from modules.old.chat_helpers import get_filepath, display_chat_history, truncate_chat_history
from modules.old.input_transformers import transform_input
from modules.utils import get_filename_without_extension

# Initialize console logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class LLMConfig(BaseModel):
    """
    Configuration class for managing the settings and parameters of the chat application.

    Attributes:
        model (str): The model type, e.g., "gpt-3.5-turbo".
        context_limit (int): Limit for the conversation context.
        default_input (str): Default input file path.
        ai_prefix (Optional[str]): Prefix for the AI's responses.
        transformations (Optional[List[InputTransformer]]): List of transformations to apply to inputs.
        max_tokens (Optional[int]): Maximum number of tokens for each response.
        temperature (Optional[float]): Temperature setting for the AI.
        top_p (Optional[float]): Top-p setting for the AI.
        n (Optional[int]): Number of completions to generate.
        stop (Optional[str]): Stop sequence for the AI.
        presence_penalty (Optional[float]): Presence penalty setting.
        frequency_penalty (Optional[float]): Frequency penalty setting.
    """
    # LLM backend service and which model to use
    llm_backend: Optional[str] = Field(default="OpenAI")
    model_config: Optional[dict] = None  # handle defaults in __init__

    # Generation parameters (may vary by backend and model)
    max_tokens: Optional[int] = Field(default=500)
    temperature: Optional[float] = Field(default=1.0)
    top_p: Optional[float] = Field(default=1.0)
    n: Optional[int] = None
    stop: Optional[str]= None
    presence_penalty: Optional[float]= None
    frequency_penalty: Optional[float] = None

    # # For local conversation management  # MOVE TO CONVERSATION ENGINE
    # context_limit: Optional[int] = Field(default=1500)
    # user_prefix: Optional[str] = Field(default="User: ")
    # ai_prefix: Optional[str] = Field(default="Assistant: ")
    # user_transformations: Optional[list] = Field(default_factory=list)
    # ai_transformations: Optional[list] = Field(default_factory=list)
    
    def __init__(self, **data):
        super().__init__(**data)
        # Set default model config based on backend
        if self.model_config is None:
            if self.llm_backend == "OpenAI":
                self.model_config = {"model": "gpt-3.5-turbo"}
            else:
                self.model_config = {}

    @classmethod
    def load_config(cls, json_file_path: str, yaml_file_path: dict = "config.yml"):
        logger.info(f"Creating LLMConfig from {json_file_path} and {yaml_file_path}")
        # First load yaml config
        with open(yaml_file_path, 'r') as stream:
            yaml_config = yaml.safe_load(stream)
        # then json config
        with open(json_file_path, 'r') as file:
            json_config = json.load(file).get('configuration', {})
        # merge them
        merged_config = {**yaml_config, **json_config}
        logger.info(f"LLMConfig input parameters: {merged_config}")

        # Create LLMConfig
        try:
            chat_config = cls(**merged_config)
            chat_config_json = json.dumps(chat_config.dict(), indent=4, default=pydantic_encoder)
            logger.info(f"LLMConfig parameters: {chat_config_json}")
        except ValidationError as e:
            logger.error(f"Validation errors: {e.errors()}")
            for error in e.errors():
                logger.error(f"Field: {error['loc'][0]}, Error: {error['msg']}")
            raise
        except Exception as e:
            logger.error(f"Failed to create LLMConfig from {merged_config}: {e}")
            raise

        # # Log LLMConfig with nice formatting:
        # logger.info(f"LLMConfig parameters: {chat_config.model_json_schema(indent=4)}")
        
        return chat_config

    def save_to_json(self, file_path: str):
        with open(file_path, 'w') as file:
            json.dump(self.dict(), file, indent=4)

class LLMManager:
    """
    Manages chat interactions, processing user inputs and generating responses.

    This class handles the chat configuration, manages the chat history, 
    and interacts with the LLM to generate responses.

    Attributes:
        config (LLMConfig): Configuration for the chat interaction.
        chat_history (list): History of the chat conversation.
    """
    
    def __init__(self, json_config_path: str):
        """
        Initializes the LLMManager with the specified chat configuration JSON file.

        Args:
            json_config_path (str): Path to the chat configuration JSON file.
        """
        self.config = LLMConfig.load_config(json_config_path)
        self.chat_history = self.load_chat_history(json_config_path)

    def load_chat_history(self, json_config_path: str) -> list:
        """
        Loads the chat history from the specified JSON file.

        Args:
            json_config_path (str): Path to the chat configuration JSON file.

        Returns:
            list: The loaded chat history.
        """
        with open(json_config_path, 'r') as file:
            data = json.load(file)
        return data.get('conversation', [])

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
            num_tokens = count_tokens(content)

        self.chat_history.append({
            "role": role,
            "content": content,
            "timestamp": timestamp,
            "num_tokens": num_tokens,
            "truncated": truncated
        })

    def generate_prompt(self, user_input: str) -> str:
        """
        Transform user input into the prompt .
        """
        # There could be all kinds of transformations needed, adding system prompts, etc.
        # But for now we just do the transformations here
        transformed_input = transform_input(user_input, self.config.transformations)
        return transformed_input

    def truncate_history(self):
        """
        Truncates the chat history based on the context limit.
        """
        self.chat_history = truncate_chat_history(self.chat_history, self.config.context_limit, self.config.max_tokens)

    def save_chat_history(self, output_path: str):
        """
        Saves the chat history to the specified JSON file.

        Args:
            output_path (str): Path to save the updated chat history.
        """
        with open(output_path, 'w') as file:
            json.dump({"conversation": self.chat_history, "configuration": self.config.dict()}, file, indent=4)

    async def interact_with_llm(self, api_key: str, prompt: str) -> str:
        """
        Interacts with the LLM using the provided prompt and generates a response.

        Args:
            api_key (str): API key for the LLM.
            prompt (str): The prompt to send to the LLM.

        Returns:
            str: The response from the LLM.
        """
        history_items = [item for item in self.chat_history if not item.get('truncated', False) or item.get('protected', False)]
        chat_coroutine = custom_streaming_chat(api_key, prompt, self.config.dict(), history_items, logger)
        complete_response = ""
        ai_prefix = self.config.ai_prefix
        first_message = True

        try:
            async for chunk in chat_coroutine:
                if isinstance(chunk, dict):
                    if "error" in chunk:
                        print(f"\nError: {chunk['error']}\n")
                        break  # Exit this try block to re-prompt the user
                    else:
                        complete_response = chunk.get("complete_message", "")
                else:
                    if first_message:
                        print(f"{ai_prefix}", end="", flush=True)
                        first_message = False
                    print(f"{chunk}", end="", flush=True)
        except KeyboardInterrupt:
            print("Your query has been canceled. You may enter a new one.")
            logger.info("User query canceled.")

        return complete_response


def parse_command_line_args():
    """
    Parses command-line arguments for input and output JSON filenames.

    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Input JSON filename for chat history.")
    parser.add_argument("--output", help="Output JSON filename for chat history.")
    return parser.parse_args()

def setup_logging(output_filepath):
    """
    Sets up logging to file and console.

    Args:
        output_filepath (str): File path for the output JSON, used to determine log file name.
    """
    log_filename = os.path.basename(output_filepath).replace('.json', '.log')
    log_filepath = os.path.join("logs", log_filename)
    logging.basicConfig(filename=f'logs/{log_filepath}', level=logging.INFO)
    logger.addHandler(logging.FileHandler(log_filepath))
    logger.info(f"Logs filename: {log_filepath}")

def console_input_provider(prompt: str) -> str:
    try:
        return input(prompt)
    except KeyboardInterrupt:
        return None
    

async def interactive_session(api_key: str, llm_manager: LLMManager, output_filepath: str):
    """
    Manages the interactive chat session.

    Args:
        api_key (str): API key for the LLM.
        llm_manager (LLMManager): The chat engine managing the session.
        output_filepath (str): Path to the output JSON file.
    """
    while True:
        try:
            user_input = console_input_provider("\n\nYou: ")
            if user_input is None:
                user_decision = input("Cancel last query? (yes/no): ")
                if user_decision.lower() == 'yes':
                    if len(llm_manager.chat_history) >= 2:
                        llm_manager.chat_history = llm_manager.chat_history[:-2]
                    display_chat_history(llm_manager.chat_history)
                    continue
                else:
                    continue  # Continue to get new input in case of 'no' or other input

            llm_prompt = llm_manager.generate_prompt(user_input)
            llm_manager.add_message_to_history("user", llm_prompt)
            os.system('cls' if os.name == 'nt' else 'clear')
            display_chat_history(llm_manager.chat_history)

            llm_output = await llm_manager.interact_with_llm(api_key, llm_prompt)
            llm_manager.add_message_to_history("assistant", llm_output)

            llm_manager.truncate_history()

        except KeyboardInterrupt:
            logger.info("User forced exit. Exiting program.")
            break

    llm_manager.save_chat_history(output_filepath)

def run_interactive_cli_session(input_filepath, output_filepath):
    """
    Runs the interactive CLI session.

    Args:
        input_filepath (str): Path to the input JSON file.
        output_filepath (str): Path to the output JSON file.
    """

    # Determine input filepath
    # Get default input filepath from config.yml's "default_input", if found
    default_input_filepath = None
    try:
        if os.path.exists("config.yml"):
            with open("config.yml", 'r') as stream:
                yaml_config = yaml.safe_load(stream)
            default_input_filepath = yaml_config.get("default_input", None)
    except Exception as e:
        logger.info(f"Failed to load default input filepath from config.yml: {e}")
        default_input_filepath = None
    # Now request that user determine input filepath
    while input_filepath is None:
        input_filepath = get_filepath(
            input_filepath, 
            prompt="Enter the name for the input JSON", 
            default_value=default_input_filepath,
            is_input=True
        )

    # Determine output filepath
    default_output_filename = f"{get_filename_without_extension(input_filepath)}-{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
    default_output_filepath = os.path.join("chat_histories", default_output_filename)
    output_filepath = get_filepath(
        output_filepath, 
        prompt="Enter the name for the output JSON", 
        default_value=default_output_filepath
    )


    # Ensure directories exist
    os.makedirs("logs", exist_ok=True)
    os.makedirs(os.path.dirname(input_filepath), exist_ok=True)
    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

    # Run the interactive chat session
    print(input_filepath)
    llm_manager = LLMManager(input_filepath)
    setup_logging(output_filepath)
    api_key = os.getenv("OPENAI_API_KEY")
    asyncio.run(interactive_session(api_key, llm_manager, output_filepath))

if __name__ == "__main__":
    args = parse_command_line_args()
    run_interactive_cli_session(args.input, args.output)
