import json
import asyncio
import os
import argparse
import logging
from datetime import datetime
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

from modules.old.app_engine import GameEngine
from modules.old.streamingapi import custom_streaming_chat, count_tokens
from modules.old.chat_helpers import get_filepath, display_chat_history, truncate_chat_history, load_config, convert_to_config_obj
from modules.old.input_transformers import cast_to_transformer_obj, transform_input

# Load environment variables
load_dotenv()

# Initialize console logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# AppProfile and State classes remain the same as previously defined

class Configuration(BaseModel):
    """
    Configuration class for managing the settings and parameters of the chat and LLM interaction.

    This class serves as a structured way to manage configuration parameters for the chat
    system, replacing the traditional dictionary-based approach with a more robust and
    validated BaseModel.

    Attributes are based on the previous 'config_dict' and should include all relevant
    configuration settings such as model, max_tokens, temperature, etc.
    """
    model: str
    default_input: str
    ai_prefix: str
    max_tokens: int
    temperature: float
    top_p: float
    n: int
    stop: Optional[str]
    presence_penalty: float
    frequency_penalty: float
    transformations: Optional[list]  # List of transformation settings

    def model_dump(self):
        """
        Converts the Configuration instance to a dictionary, excluding unset optional fields.
        """
        return {k: v for k, v in self.dict().items() if v is not None}

# GameEngine class remains the same as previously defined

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

async def interactive_app_session(api_key: str, app_engine: GameEngine, config: Configuration):
    """
    Run an interactive chat session with the assistant, integrating game engine interactions.

    Args:
        api_key (str): API key for the LLM.
        app_engine (GameEngine): The game engine instance managing the game state.
        config (Configuration): Configuration instance with chat and LLM settings.
    """
    while True:
        try:
            user_input = console_input_provider("\n\nYou: ")
            if user_input is None:
                # Handle interruption or cancellation
                continue

            # Transform input if necessary
            if config.transformations:
                user_input = transform_input(user_input, config.transformations)

            # Clear the screen for better readability
            os.system('cls' if os.name == 'nt' else 'clear')
            display_chat_history(app_engine.app_state.conversation)

            # Process user input with game engine
            app_engine.parse_player_input(user_input)

            # Generate LLM prompt
            llm_prompt = app_engine.generate_llm_prompt(user_input)

            # Interact with the LLM and update game state
            llm_output = await interact_with_llm(api_key, llm_prompt, config)
            app_engine.update_from_llm_output(llm_output)

            # Save game state after each interaction
            app_engine.export_app_state_to_json(config.default_input)

        except KeyboardInterrupt:
            logger.info("User forced exit. Exiting program.")
            break

def console_input_provider(prompt: str) -> Optional[str]:
    """
    Obtain input from the console with error handling for interruptions.

    Args:
        prompt (str): The prompt to display to the user.

    Returns:
        Optional[str]: The user's input or None if interrupted.
    """
    try:
        return input(prompt)
    except KeyboardInterrupt:
        return None

async def interact_with_llm(api_key: str, prompt: str, config: Configuration) -> str:
    """
    Interacts with the LLM using the provided prompt and configuration.

    Args:
        api_key (str): API key for the LLM.
        prompt (str): The prompt to send to the LLM.
        config (Configuration): Configuration instance with chat and LLM settings.

    Returns:
        str: The LLM's response.
    """
    # TODO: Implement the interaction with the LLM using `custom_streaming_chat` or similar function
    pass



def run_interactive_cli_game(input_filepath, output_filepath):
    """
    Runs the interactive CLI session for the game.

    This function sets up the necessary configurations and initializes the GameEngine to start
    the interactive game session. It handles command line arguments for input and output JSON files.

    Args:
        input_filepath (str): Path to the input JSON file containing the game profile and game state.
        output_filepath (str): Path to the output JSON file where the updated game state will be saved.
    """
    # Determine input and output file paths
    input_filepath = get_filepath(input_filepath, "Enter the name for the input JSON", default_value=config.default_input, is_input=True)
    output_filepath = get_filepath(output_filepath, "Enter the name for the output JSON", default_value=datetime.now().strftime("%Y%m%d%H%M%S"))

    # Ensure directories exist
    os.makedirs("logs", exist_ok=True)
    os.makedirs(os.path.dirname(input_filepath), exist_ok=True)
    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

    # Load game and chat configuration
    config = Configuration(**load_config())
    setup_logging(output_filepath)

    # Initialize GameEngine with the input JSON file
    app_engine = GameEngine(input_filepath)

    # Run the interactive chat and game session
    api_key = os.getenv("OPENAI_API_KEY")
    asyncio.run(interactive_app_session(api_key, app_engine, config))

if __name__ == "__main__":    
    args = parse_command_line_args()
    run_interactive_cli_game(args.input, args.output)
