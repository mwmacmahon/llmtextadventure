
from typing import Type, TypeVar, Optional, Union, Any, Dict, get_args, get_origin
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from modules.core.config import BaseConfig
import os


# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class GenerationConfig(BaseConfig):
    """
    Configuration class for common generation parameters used across LLM backends.
    Will use preset-specific schema for defaults/validation if one is provided.
    """

    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[float] = None
    stop: Optional[list] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for GenerationConfig."""
        # Find all presets in the generation_presets folder
        presets = [
            os.path.splitext(filename)[0]
            for filename in os.listdir('./config/schemas/generation/generation_presets')
        ]
        preset_name = parent_data.get("generation_preset", "default")
        # print("CLASS CREATION DEBUG INFO")
        # print(f"This class: {cls}")
        # print(f"data: {data}")
        # print(f"parent data: {parent_data}")
        # print(f"presets: {presets}")
        # print(f"preset_name: {preset_name}")
        if preset_name not in presets:
            raise ValueError(f"Invalid generation preset: {preset_name}. Valid values are: {presets}")
        preset_config_path = f"./config/schemas/generation/generation_presets/{preset_name}.yml"
        if not os.path.exists(preset_config_path):
            raise ValueError(f"Invalid generation preset: {preset_name}.")
        return preset_config_path
    