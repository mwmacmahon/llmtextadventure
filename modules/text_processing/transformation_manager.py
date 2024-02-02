
from typing import Type, TypeVar, Optional, Union, Any, Dict, get_args, get_origin
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from modules.core.config import BaseConfig
from modules.core.patterns import State
from modules.text_processing.transformation_patterns import TransformationConfig
from modules.text_processing.transformation_functions import \
    cleanup_whitespace, prepend_prefix, append_suffix

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


TRANSFORMER_FUNCTIONS = {
    'cleanup_whitespace': cleanup_whitespace,
    'prepend_prefix': prepend_prefix,
    'append_suffix': append_suffix
}


class TransformationManager:
    """
    TransformationManager manages text transformations based on configured rules.
    It applies transformations to modify or format text as required.

    Attributes:
        transformation_config (TransformationConfig): Configuration for text transformations.
    """

    def __init__(self, transformation_config: TransformationConfig):
        """
        Initializes the TransformationManager with transformation configuration.

        Args:
            transformation_config (TransformationConfig): Configuration for text transformations.
        """
        self.transformation_config = transformation_config


    def apply_single_transformation(self, transformation_name: str, text: str, state: Optional[State] = None, **kwargs) -> str:
        """
        Applies a single transformation to the text based on the given transformation name.

        Args:
            transformation_name (str): Name of the transformation to apply.
            text (str): Text to be transformed.
            state (Optional[State]): State of the conversation, passed to transformations.
            **kwargs: Additional arguments to be passed to the transformation function.

        Returns:
            str: Transformed text.
        """
        # print(f"Calling apply_single_transformation({transformation_name})")
        # Convert state to dict
        state_dict = state.model_dump() if state else {}
        # Get transformation function
        transform_func = TRANSFORMER_FUNCTIONS.get(transformation_name)
        # print(f"transform_func: {transform_func}")
        if transform_func:
            return transform_func(text, state_dict, **kwargs)
        else:
            logger.warning(f"Transformation function '{transformation_name}' not found.")
            return text

    def apply_transformation_set(self, transformation_set: str, text: str, state: Optional[State] = None, runtime_kwargs: dict = None) -> str:
        """
        Applies a set of transformations defined in the configuration to the text.

        Transformations are assumed to be of form:
            output_text = some_transformation(input_text, state_dict={}, **kwargs)
        The state is intended to be used in a read-only manner. See parsing_manager
        for editing the state based on input text.

        Args:
            transformation_set (str): Name of the transformation set from the config file.
            text (str): Text to be transformed.
            state (Optional[State]): State of the conversation, passed to transformations.
            runtime_kwargs (Optional[dict]): Additional/overriding args to be passed to
                the transformation functions. Should be of form:
                {
                    'transformation_name': {
                        'arg_name': arg_value
                    }
                }
                It will apply to any transformation in the set that has the specified
                name, and will override any arguments specified in the TransformationConfig.

        Returns:
            str: Transformed text.
        """
        # print(f"Calling apply_transformation_set({transformation_set})")
        # Retrieve transformation list from configuration
        try:
            transformation_list = getattr(self.transformation_config, transformation_set)
        except AttributeError:
            logger.warning(f"Transformation set '{transformation_set}' not found.")
            return text
        
        # Apply each transformation
        for transformation_dict in transformation_list:
            if transformation_dict['name'] in TRANSFORMER_FUNCTIONS:
                # Get args from config, then override with runtime args if they exist
                # print(f"transform_func: {transformation_dict['name']}")
                args = transformation_dict.get('args', {})
                if runtime_kwargs and transformation_dict['name'] in runtime_kwargs:
                    args.update(runtime_kwargs[transformation_dict['name']])
                text = self.apply_single_transformation(transformation_dict['name'], text, state, **args)
            else:
                logger.warning(f"Transformation function '{transformation_dict['name']}' not found.")

        return text
    