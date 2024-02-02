
from typing import Type, TypeVar, Optional, Union, List, Any, Dict, get_args, get_origin, get_type_hints, ClassVar
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Protocol
import asyncio
import yaml
import inspect
import importlib

from modules.core.config import BaseConfig
# from modules.core.engine import ConversationEngine

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

T = TypeVar('T', bound='BaseConfig')
TEngine = TypeVar('TEngine', bound='ConversationEngine')

# Global mappings from interface types 
# to InterfaceConfig and Interface classes
# Left: Interface Type
# Right: Interface Class
INTERFACE_CLASS_MODULES = {
    "api": "modules.interfaces.api",
    "cli": "modules.interfaces.cli",
    "webui": "modules.interfaces.webui"
}
INTERFACE_CONFIGS= {
    "api": "APIInterfaceConfig",
    "cli": "CLIInterfaceConfig",
    "webui": "WebInterfaceConfig"
}
INTERFACE_CLASSES = {
    "api": "APIInterface",
    "cli": "CLIInterface",
    "webui": "WebInterface"
}

class InterfaceConfig(BaseConfig):
    """
    Base configuration class for interfaces.
    Does not need to be subclassed for each specific interface, because a different
    schema is automatically used for each interface type, and pydantic will validate
    the class attributes against the schema.
    Inherits from BaseConfig and defines specific fields relevant to interfaces.
    Do NOT use any attributes whose names start with "model_" or it will cause errors
    """
    @classmethod
    def get_class(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> T:
        """
        Get the class to be created. Usuaully this is just cls, but it can be overridden
        in certain cases, such as when the class to be created depends on the parent data.
        (e.g., InterfaceConfig depends on interface_type)

        Args:
            data (dict, optional): Overriding attribute values for this class.
            parent_data (dict, optional: the final non-object attributes of the parent configuration.

        Returns:
            cls: The class to be created
        """
        interface_type = "CLI" # Default
        if parent_data and "interface_type" in parent_data:
            interface_type = parent_data["interface_type"]
        if interface_type in INTERFACE_CONFIGS.keys():
            new_class = INTERFACE_CONFIGS[interface_type]
        else:
            raise ValueError(
                f"Invalid interface type: {interface_type}. Valid values are {INTERFACE_CONFIGS.keys()}"
            )
        
        # Convert to actual class (but we can't import it - that would
        # cause a circular import!)
        module_name = INTERFACE_CLASS_MODULES[interface_type]
        # print(module_name)
        # print(new_class)
        module = importlib.import_module(module_name)
        new_class_obj = getattr(module, new_class)
        # print(new_class_obj)
        return new_class_obj
        # return globals()[new_class]  # doesn't work




# Don't use pydantic for this one, causes headaches
class Interface:
    """
    Base class for specific interface implementations.
    Subclasses should implement the generate_response method for different interfaces.
    """
    interface_config: InterfaceConfig

    def __init__(self, interface_config: InterfaceConfig):
        """
        Initializes the Interface with specific interface configuration.

        Args:
            interface_config (InterfaceConfig): The configuration for the interface.
        """
        ## Use super().__init__ in subclasses to call this
        # super().__init__(interface_config=interface_config)  # Initialize the BaseModel (removed)
        self.interface_config = interface_config
    
    def run(self, engine: TEngine):
        """
        Exists as a passthrough to run_async() via asyncio.run(), 
        which is the main conversation loop.

        Args:
            engine (ConversationEngine): The engine managing the conversation logic.
        """
        asyncio.run(self.run_async(engine))

    def run_async(self, engine: TEngine):
        raise NotImplementedError

    def read_input(self, input_prompt: str = ""):
        raise NotImplementedError

    def write_output(self, message: str, output_prefix: str = ""):
        raise NotImplementedError
    
    def display_chat_history(self, chat_history: List[Dict[str, str]]):
        raise NotImplementedError
    

