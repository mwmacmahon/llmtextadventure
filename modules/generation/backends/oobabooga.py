
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type, Dict, Any
from modules.core.config import BaseConfig
from modules.generation.backend_patterns import Backend, BackendConfig
from modules.generation.generation_patterns import GenerationConfig

# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OobaboogaBackendConfig(BackendConfig):
    """
    Configuration class for the Oobabooga backend. Inherits from BackendConfig.
    Inherits from BaseConfig and defines specific fields relevant to LLM Backend.
    Do NOT use any attributes whose names start with "model_" or it will cause errors
    """

    name_of_model: str
    oobabooga_settings: dict

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for OobaboogaBackendConfig."""
        return "./config/schemas/generation/backends/oobabooga.yml"


class OobaboogaBackend(Backend):
    """
    Oobabooga specific Backend implementation.

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

    def generate_response(self, prompt: str, generation_config: GenerationConfig) -> str:
        """
        Generates a response from Oobabooga based on the given prompt and generation configuration.

        Args:
            prompt (str): The prompt to send to Oobabooga.
            generation_config (GenerationConfig): Configuration for generation parameters.

        Returns:
            str: The response generated by Oobabooga.
        """
        params_dict = generation_config.model_dump()  # Guaranteed to have all the required params
        # Placeholder for Oobabooga specific logic to generate a response
        # This would include making a request to Oobabooga's API using the provided prompt
        # and generation parameters, and then returning the response.
        pass