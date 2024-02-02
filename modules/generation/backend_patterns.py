
from typing import Type, TypeVar, Optional, Union, Any, Dict, get_args, get_origin
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Protocol
from modules.core.config import BaseConfig
from modules.generation.generation_patterns import GenerationConfig
import importlib

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

T = TypeVar('T', bound='BaseConfig')

# Global mappings from backend types 
# to BackendConfig and Backend classes
# Left: Conversation Type
# Right: Backend Class
BACKEND_CLASS_MODULES = {
    "OpenAI": "modules.generation.backends.openai",
    "HFTGI": "modules.generation.backends.hftgi",
    "Oobabooga": "modules.generation.backends.oobabooga"
}
BACKEND_CONFIGS= {
    "OpenAI": "OpenAIBackendConfig",
    "HFTGI": "HFTGIBackendConfig",
    "Oobabooga": "OobaboogaBackendConfig"
}
BACKEND_CLASSES = {
    "OpenAI": "OpenAIBackend",
    "HFTGI": "HFTGIBackend",
    "Oobabooga": "OobaboogaBackend"
}

class BackendConfig(BaseConfig):
    """
    Base configuration class for Language Model (LLM) backend settings and parameters.
    Does not need to be subclassed for each specific backend, because a different
    schema is automatically used for each backend type, and pydantic will validate
    the class attributes against the schema.
    Inherits from BaseConfig and defines specific fields relevant to LLM Backend.
    Do NOT use any attributes whose names start with "model_" or it will cause errors
    """
    @classmethod
    def get_class(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> T:
        """
        Get the class to be created. Usuaully this is just cls, but it can be overridden
        in certain cases, such as when the class to be created depends on the parent data.
        (e.g., BackendConfig depends on backend_config_type)

        Args:
            data (dict, optional): Overriding attribute values for this class.
            parent_data (dict, optional: the final non-object attributes of the parent configuration.

        Returns:
            cls: The class to be created
        """
        backend_config_type = "OpenAI" # Default
        if parent_data and "backend_config_type" in parent_data:
            backend_config_type = parent_data["backend_config_type"]
        if backend_config_type in BACKEND_CONFIGS.keys():
            new_class = BACKEND_CONFIGS[backend_config_type]
        else:
            raise ValueError(
                f"Invalid backend type: {backend_config_type}. Valid values are {BACKEND_CONFIGS.keys()}"
            )
        
        # Convert to actual class (but we can't import it - that would
        # cause a circular import!)
        module_name = BACKEND_CLASS_MODULES[backend_config_type]
        # print(module_name)
        # print(new_class)
        module = importlib.import_module(module_name)
        new_class_obj = getattr(module, new_class)
        # print(new_class_obj)
        return new_class_obj
        # return globals()[new_class]  # doesn't work



    # @classmethod
    # def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
    #     """Provides the path to the yaml schema for BackendConfig."""
    #     backend_config_type = "OpenAI" # Default
    #     if parent_data and "backend_config_type" in parent_data:
    #         backend_config_type = parent_data["backend_config_type"]
    #     if backend_config_type == "HFTGI":
    #         return "./config/schemas/generation/backends/hftgi.yml"
    #     elif backend_config_type == "Oobabooga":
    #         return "./config/schemas/generation/backends/oobabooga.yml"
    #     elif backend_config_type == "OpenAI":
    #         return "./config/schemas/generation/backends/openai.yml"
        
    #     raise ValidationError(
    #         f"Invalid backend type: {backend_config_type}. Valid values are {BACKEND_CLASSES.keys()}"
    #     )


# Protocol to suggest that a class is a Backend.
# This is used to type hint ____Backend classes in the LLMManager.
class Backend(BaseModel):
    """
    Base class for specific backend implementations.
    Subclasses should implement the generate_response method for different backends.
    """
    backend_config: BackendConfig

    def __init__(self, backend_config: BackendConfig):
        """
        Initializes the Backend with specific backend configuration.

        Args:
            backend_config (BackendConfig): The configuration for the backend.
        """
        ## Use super().__init__ in subclasses to call this
        super().__init__(backend_config=backend_config)  # Initialize the BaseModel
        self.backend_config = backend_config

    async def generate_response(self, prompt: str, chat_history: list, generation_config: GenerationConfig, prefix: str) -> str:
        """
        Generates a response based on the given prompt and generation configuration.

        Args:
            prompt (str): The prompt to send to the backend.
            chat_history (list): The chat history to send to the backend.
            generation_config (GenerationConfig): The configuration for generation parameters.
            prefix (str): The prefix to send to the backend.

        Returns:
            str: The response generated by the backend.
        """
        pass

