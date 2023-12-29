
from typing import Type, TypeVar, Optional, Union, List, Any, Dict, get_args, get_origin
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from modules.core.config import BaseConfig


# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TransformationConfig(BaseConfig):
    """
    Configuration class for transformation functions, including the list of 
    transformation functions to use and their fixed parameters.
    """

    user_input_transformations: List[Dict[str, Any]]
    llm_output_transformations: List[Dict[str, Any]]

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        return "./config/schemas/text_processing/transformation_config.yml"
