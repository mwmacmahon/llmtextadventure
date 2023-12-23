import asyncio
import os
import json
import logging
import argparse
from datetime import datetime
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import yaml

from modules.old.streamingapi import custom_streaming_chat, count_tokens
from modules.old.chat_helpers import get_filepath, display_chat_history, truncate_chat_history
from modules.old.input_transformers import transform_input

# Initialize console logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class ChatConfig(BaseModel):
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
    model: str = Field(...)
    context_limit: int = Field(...)
    default_input: str = Field(...)
    ai_prefix: str = Field("Assistant: ")
    transformations: list = Field([])
    max_tokens: int = Field(100)
    temperature: float = Field(1.0)
    top_p: float = Field(1.0)
    n: int = Field(1)
    stop: str = Field(None)
    presence_penalty: float = Field(0.0)
    frequency_penalty: float = Field(0.0)
    

    @classmethod
    def load_config(cls, json_file_path: str, yaml_file_path: dict = "config.yml"):
        # First load yaml config
        with open(yaml_file_path, 'r') as stream:
            yaml_config = yaml.safe_load(stream)
        # then json config
        with open(json_file_path, 'r') as file:
            json_config = json.load(file).get('configuration', {})
        merged_config = {**yaml_config, **json_config}
        return cls(**merged_config)

    def save_to_json(self, file_path: str):
        with open(file_path, 'w') as file:
            json.dump(self.dict(), file, indent=4)

class ChatEngine:
    """
    Manages chat interactions, processing user inputs and generating responses.

    This class handles the chat configuration, manages the chat history, 
    and interacts with the LLM to generate responses.

    Attributes:
        config (ChatConfig): Configuration for the chat interaction.
        chat_history (list): History of the chat conversation.
    """
    
    def __init__(self, json_config_path: str):
        """
        Initializes the ChatEngine with the specified chat configuration JSON file.

        Args:
            json_config_path (str): Path to the chat configuration JSON file.
        """
        self.config = ChatConfig.load_config(json_config_path)
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
    

async def interactive_session(api_key: str, chat_engine: ChatEngine, output_filepath: str):
    """
    Manages the interactive chat session.

    Args:
        api_key (str): API key for the LLM.
        chat_engine (ChatEngine): The chat engine managing the session.
        output_filepath (str): Path to the output JSON file.
    """
    while True:
        try:
            user_input = console_input_provider("\n\nYou: ")
            if user_input is None:
                user_decision = input("Cancel last query? (yes/no): ")
                if user_decision.lower() == 'yes':
                    if len(chat_engine.chat_history) >= 2:
                        chat_engine.chat_history = chat_engine.chat_history[:-2]
                    display_chat_history(chat_engine.chat_history)
                    continue
                else:
                    continue  # Continue to get new input in case of 'no' or other input

            chat_engine.add_message_to_history("user", user_input)
            os.system('cls' if os.name == 'nt' else 'clear')
            display_chat_history(chat_engine.chat_history)

            llm_output = await chat_engine.interact_with_llm(api_key, user_input)
            chat_engine.add_message_to_history("assistant", llm_output)

            chat_engine.truncate_history()

        except KeyboardInterrupt:
            logger.info("User forced exit. Exiting program.")
            break

    chat_engine.save_chat_history(output_filepath)

def run_interactive_cli_session(input_filepath, output_filepath):
    """
    Runs the interactive CLI session.

    Args:
        input_filepath (str): Path to the input JSON file.
        output_filepath (str): Path to the output JSON file.
    """
    os.makedirs("logs", exist_ok=True)
    os.makedirs(os.path.dirname(input_filepath), exist_ok=True)
    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

    chat_engine = ChatEngine(input_filepath)
    setup_logging(output_filepath)
    api_key = os.getenv("OPENAI_API_KEY")
    asyncio.run(interactive_session(api_key, chat_engine, output_filepath))

if __name__ == "__main__":
    args = parse_command_line_args()
    run_interactive_cli_session(args.input, args.output)
