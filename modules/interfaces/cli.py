
from typing import Type, TypeVar, Optional, Union, List, Any, Dict, get_args, get_origin, get_type_hints, ClassVar
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
import yaml
import inspect
import importlib
import asyncio

from modules.interfaces.patterns import Interface, InterfaceConfig
# from modules.core.engine import ConversationEngine

# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEngine = TypeVar('TEngine', bound='ConversationEngine')

class CLIInterfaceConfig(InterfaceConfig):
    """"""
    interface_mode: str

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for HFTGIBackendConfig."""
        return "./config/schemas/interfaces/cli.yml"


class CLIInterface(Interface):
    """
    CLI specific Interface implementation.

    Attributes:
        interface_config (InterfaceConfig): Configuration specific to CLI.
    """
    def __init__(self, interface_config):
        super().__init__(interface_config)

    async def run_async(self, engine: TEngine):
        """
        Main conversation loop for the CLI interface.Can parse user input to do 
        the equivalent of clicking on buttons even though it only uses user text 
        inputs. All logic is passed off to async Engine methods, which must be run 
        via asyncio.run() or similar.

        Args:
            engine (ConversationEngine): The engine managing the conversation logic.
        """

        while True:
            try:
                # Get user input
                user_input = self.read_input("\n\nYou: ")
                if user_input.strip() == "":
                    user_decision = self.read_input("Cancel last query? (yes/no): ")
                    if user_decision.lower() == 'yes':
                        if len(engine.state.chat_history) >= 2:
                            engine.state.chat_history = engine.state.chat_history[:-2]
                        self.display_chat_history(engine.state.chat_history)
                        continue

                # Handles all pulling and displaying of data in preparation for 
                # next user input
                await self.process_user_input(engine, user_input)

            except KeyboardInterrupt:
                logger.info("User forced exit. Exiting program.")
                break

    async def process_user_input(self, engine: TEngine, user_input: str):
        """
        Process the user input asynchronously and display the output.

        Args:
            engine (ConversationEngine): The engine to process the input.
            user_input (str): The user's input text.
        """
        # await self.process_user_input(engine, user_input)
        async for output in engine.query(user_input):
            try:
                if "status" in output:
                    if output["status"] == "finished":
                        # Do any postprocessing needed here

                        # Clear the screen and display the final processed chat 
                        # history in case there were changes from the raw output
                        self.display_chat_history(engine.state.chat_history)
                    else:
                        # Custom streaming display logic could go here
                        pass
            except KeyError as e:
                raise ValueError(f"Error occurred parsing engine.query(): {e}")


    def read_input(self, input_prompt: str = ""):
        return input(input_prompt)

    def write_output(self, message, output_prefix: str = ""):
        print(message)

    def display_chat_history(self, chat_history: List[Dict[str, str]]) -> None:
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
        