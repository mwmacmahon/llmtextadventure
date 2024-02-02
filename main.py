import argparse
from modules.startup import run_local
import os
# from modules.old.interactive_cli_session import run_interactive_cli_session
# from modules.interactive_cli_game import run_interactive_cli_game
# import asyncio

import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

def setup_logging(output_filepath: str):
    """
    Sets up logging to file and console.

    Args:
        output_filepath (str): File path for the output JSON, used to determine log file name.
    """
    if not output_filepath:
        raise ValueError("Output filepath cannot be empty")
    log_filename = os.path.basename(output_filepath).replace('.json', '.log')
    log_filepath = os.path.join("logs", log_filename)
    logging.basicConfig(filename=f'logs/{log_filepath}', level=logging.INFO)
    logger.addHandler(logging.FileHandler(log_filepath))
    logger.info(f"Logs filename: {log_filepath}")

def main():
    """
    Main entry point for the text adventure game and chat application.

    This script acts as a command-line interface to run different parts of the application,
    such as conversation, game, or autochat modes. It parses command-line arguments to
    determine the mode of operation and passes appropriate arguments to each module.

    Example usage:
        - For conversation mode:
            python main.py --mode conversation --input path/to/input/json --output path/to/output/json
        - For game mode:
            python main.py --mode game --input path/to/app_profile.json --output path/to/app_state.json
    """
    parser = argparse.ArgumentParser(description='Main CLI app for running individual apps')
    parser.add_argument('--mode', choices=['chat', 'samplegamea', 'samplegameb', 'autochat'], help='Mode of the app to run')
    parser.add_argument('--ui', choices=['cli', 'webui', 'SampleGameB', 'autochat'], default="cli", help='Input JSON filename for game profile or chat history.')
    parser.add_argument('--input', required=True, help='Input JSON filename for game profile or chat history.')
    parser.add_argument('--output', required=True, help='Output JSON filename for game state or chat history.')

    args = parser.parse_args()
    setup_logging(args.output)

    run_local(
        app_name=args.mode,
        interface_type=args.ui,
        input_path=args.input,
        output_path=args.output
    )

if __name__ == '__main__':
    main()


# if __name__ == "__main__":
#     engine = load_engine("Chat", "./testconfig-output.json")
#     print("Finished loading!")
#     # engine = load_engine("Chat")

#     engine.print_yaml()
#     engine.save_yaml("./testconfig-output.yml")
#     engine.save_json("./testconfig-output.json")