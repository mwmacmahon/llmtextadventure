import asyncio
import os
import json
import argparse
import logging
from datetime import datetime
from dotenv import load_dotenv

from modules.old.streamingapi import custom_streaming_chat, count_tokens
from modules.old.chat_helpers import get_filepath, display_chat_history, truncate_chat_history, load_config, convert_to_config_obj

# Assuming the transform_input function is in input_transformers.py
from modules.old.input_transformers import cast_to_transformer_obj, transform_input

load_dotenv()

# Initialize console logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument("--input", help="Input JSON filename for chat history.")
parser.add_argument("--output", help="Output JSON filename for chat history.")
args = parser.parse_args()

# Load YAML configuration
config_dict = load_config()
logger.debug("Raw config dict:")
logger.debug(config_dict)
config = convert_to_config_obj(config_dict)
logger.debug("Converted config:")
logger.debug(config)

# Determine input and output filenames
input_filepath = get_filepath(
    args.input,
    "Enter the name for the input JSON: ", 
    config.default_input
)
output_filepath = get_filepath(
    args.output,
    "Enter the name for the output JSON (default is timestamp): ",
    datetime.now().strftime("%Y%m%d%H%M%S")
)

# Setup logging
log_filename = os.path.basename(output_filepath).replace('.json', '.log')
log_filepath = os.path.join("logs", log_filename)
logging.basicConfig(filename=f'logs/{log_filepath}', level=logging.INFO)
logger.addHandler(logging.FileHandler(log_filepath))

logger.info(f"Input filename:  {input_filepath}")
logger.info(f"Output filename: {output_filepath}")
logger.info(f"Logs filename:   {log_filepath}")

# Ensure directories exist
logger.info(f"Ensuring directories exist...")
os.makedirs("logs", exist_ok=True)
os.makedirs(os.path.dirname(input_filepath), exist_ok=True)
os.makedirs(os.path.dirname(output_filepath), exist_ok=True)


# Load chat data
chat_data = {}
chat_history = []

try:
    with open(input_filepath, 'r') as f:
        logger.info("Loading chat history...")
        chat_data = json.load(f)
        chat_history = chat_data.get('conversation', [])
        chat_config_dict = chat_data.get('configuration', {})

        logger.info("JSON partial config dict:")
        logger.info(chat_config_dict)
        config_dict.update(chat_config_dict)
        logger.info("Full combined config dict:")
        logger.info(config_dict)
        config = convert_to_config_obj(config_dict)
        logger.info("Full combined config obj:")
        logger.info(config)

        # keep the original transformations around:
        transformations_dict = config_dict.get("transformations")

        # now convert ChatConfig back to dict but use the raw input transformations instead
        config_dict = config.model_dump()
        config_dict["transformations"] = transformations_dict
        logger.info("Exported config dict:")
        logger.info(config_dict)

        context_limit = config.context_limit
        max_tokens = config.max_tokens

        # Process the chat history
        for item in chat_history:
            if 'num_tokens' not in item:
                item['num_tokens'] = count_tokens(item['content'])
            if 'truncated' not in item:
                item['truncated'] = False

        chat_history = truncate_chat_history(chat_history, context_limit, max_tokens)


        # Extract transforming functions from final configuration
        transformations = config.transformations
        # transformations = [cast_to_transformer_obj(t) for t in transformations] # unnecessary, already done
        logger.info(f"Loaded transformations: {transformations}")


except FileNotFoundError:
    logger.error(f"File {input_filepath} not found. Starting with empty chat history.")
    chat_history = []

def console_input_provider(prompt: str) -> str:
    """Obtain input from the console with error handling for interruptions."""
    try:
        return input(prompt)
    except KeyboardInterrupt:
        return None

async def interactive_session(api_key: str, chat_history: list, config: dict, input_provider: callable):
    """Run an interactive chat session with the assistant, save history, and handle user interactions."""
    context_limit = config.context_limit
    max_tokens = config.max_tokens

    ## Prep the screen
    os.system('cls' if os.name == 'nt' else 'clear')
    display_chat_history(chat_history)

    ## Chat loop
    while True:
        try:
            query = input_provider("\n\nYou: ")
            if query is None:
                resp = input("Do you want to cancel and replace the last query? (yes/no): ")
                if resp.lower() == 'yes':
                    chat_history = chat_history[:-2] if len(chat_history) >= 2 else []
                    display_chat_history(chat_history)
                    continue
                else:
                    # In case of 'no' or any other input, just continue to get new input.
                    continue

            if transformations:
                query = transform_input(query, transformations)

            os.system('cls' if os.name == 'nt' else 'clear')
            display_chat_history(chat_history)
            print(f"\n\nYou: {query}\n")
            print("")

            timestamp = datetime.utcnow().isoformat() + 'Z'
            user_message = {
                "role": "user", 
                "content": query, 
                "timestamp": timestamp,
                "num_tokens": count_tokens(query),
                "truncated": False
            }
            chat_history.append(user_message)
            chat_history = truncate_chat_history(chat_history, context_limit, max_tokens)

            history_items = [
                item for item in chat_history
                if not item.get('truncated', False) or item.get('protected', False)
            ]

            chat_coroutine = custom_streaming_chat(api_key, query, config_dict, history_items, logger)
            complete_response = ""
            ai_prefix = config.ai_prefix

            first_message = True

            try:
                async for chunk in chat_coroutine:
                    if isinstance(chunk, dict):
                        if "error" in chunk:
                            print(f"\nError: {chunk['error']}\n")
                            chat_history = chat_history[:-1]  # Remove the last user message
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
                continue

            if "error" not in chunk:
                timestamp = datetime.utcnow().isoformat() + 'Z'
                new_response = {
                    "role": "assistant",
                    "content": complete_response,
                    "timestamp": timestamp,
                    "num_tokens": count_tokens(complete_response),
                    "truncated": False
                }
                chat_history.append(new_response)
                chat_history = truncate_chat_history(chat_history, context_limit, max_tokens)

                with open(output_filepath, 'w') as f:
                    output_data = {
                        "conversation": chat_history,
                        "configuration": config_dict,
                        "input": input_filepath
                    }
                    output_data["configuration"].pop("default_input", None)
                    json.dump(output_data, f, indent=4)

        except KeyboardInterrupt:
            logger.info("User forced exit. Exiting program.")
            print("Exiting program.")
            break


def run_interactive_cli_session(input_filepath, output_filepath):
    """
    Runs the interactive CLI session for the chat.

    Args:
        input_filepath (str): Path to the input JSON file containing the chat config / conversation history.
        output_filepath (str): Path to the output JSON file where the updated chat history will be saved.
    """
    ## These are currently handled at the top of the file, but that logic
    ## should be moved here.

    # # Determine input and output file paths
    # input_filepath = get_filepath(input_filepath, "Enter the name for the input JSON: ", config.default_input)
    # output_filepath = get_filepath(output_filepath, "Enter the name for the output JSON (default is timestamp): ", datetime.now().strftime("%Y%m%d%H%M%S"))

    # # Ensure directories exist
    # os.makedirs("logs", exist_ok=True)
    # os.makedirs(os.path.dirname(input_filepath), exist_ok=True)
    # os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

    # Run the interactive chat and game session
    api_key = os.getenv("OPENAI_API_KEY")

    os.system('cls' if os.name == 'nt' else 'clear')
    asyncio.run(interactive_session(api_key, chat_history, config, console_input_provider))

if __name__ == "__main__":
    run_interactive_cli_session()
