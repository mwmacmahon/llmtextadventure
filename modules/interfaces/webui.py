
from typing import Type, TypeVar, Optional, Union, List, Any, Dict, get_args, get_origin, get_type_hints, ClassVar
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
import yaml
import inspect
import importlib
import time

import gradio as gr
import threading
import queue

from modules.interfaces.patterns import Interface, InterfaceConfig
# from modules.core.engine import ConversationEngine

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

TEngine = TypeVar('TEngine', bound='ConversationEngine')


class WebInterfaceConfig(InterfaceConfig):
    """"""
    interface_mode: str

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for HFTGIBackendConfig."""
        return "./config/schemas/interfaces/webui.yml"


class WebInterface(Interface):
    input_queue: queue.Queue
    output_queue: queue.Queue
    chat_history: str  # String to store the formatted chat history

    def __init__(self, interface_config):
        super().__init__(interface_config)
        self.input_queue = queue.Queue()
        self.output_queue = queue.Queue()
        self.chat_history = ""
        self.create_gradio_interface()
    
    def run_async(self, engine: TEngine):
        """
        Put whatever it takes to start the application here. After this, 
        the program will be handled by UI callbacks that directly call
        the Engine's methods.

        Args:
            engine (ConversationEngine): The engine managing the conversation logic.
        """
        self.launch()  # ?

        # I'm sure more is needed
        return NotImplementedError

    def create_gradio_interface(self):
        def query(user_input, history):
            self.input_queue.put(user_input)
            # Return an empty string for the next input and the current chat history
            return "", self.chat_history

        self.interface = gr.Interface(
            fn=query,
            inputs=[gr.Textbox(label="Your message"), gr.State()],
            outputs=[gr.Textbox(), gr.State()],
            title="Chat with Engine",
            live=True
        )
    def read_input(self, input_prompt=""):
        return self.input_queue.get()

    def write_output(self, message, output_prefix=""):
        # Update the chat history string
        self.chat_history = f"{output_prefix}{message}\n{self.chat_history}"

    def display_chat_history(self, chat_history):
        formatted_history = "\n".join([f"{entry['role'].title()}: {entry['content']}" for entry in chat_history])
        self.chat_history = formatted_history  # Update the internal chat history string

    def launch(self):
        threading.Thread(target=self.interface.launch, daemon=True).start()
        threading.Thread(target=self.poll_and_update_history, daemon=True).start()

    def poll_and_update_history(self):
        """
        Periodically polls for updates in the chat history and refreshes the Gradio interface.
        """
        while True:
            # Check if there's an update in the chat history
            current_history = self.output_queue.get()
            if current_history != self.chat_history:
                self.chat_history = current_history
                self.interface.update(value=self.chat_history, component=self.interface.get_output_components()[1])
            time.sleep(0.5)  # Polling interval
