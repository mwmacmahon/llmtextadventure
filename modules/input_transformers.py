"""
input_transformers.py

This script defines a set of input transformation functions and a way to execute them.
"""
import logging

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Union, Any, Callable, Type


# Initialize console logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


##


class InputTransformerArgs(BaseModel):
    pass

class InputTransformer(BaseModel):
    name: str
    func: Callable
    # args: Optional[InputTransformerArgs]  # will only be implemented later

##

def cleanup_whitespace(user_input: str) -> str:
    """
    Clean up consecutive whitespaces in the user's input.

    Args:
        user_input (str): The original user input.

    Returns:
        str: User input with cleaned up whitespace.
    """
    return ' '.join(user_input.split())

class CleanupWhitespaceArgs(InputTransformerArgs):
    pass

class CleanupWhitespaceTransformer(InputTransformer):
    name: str = "cleanup_whitespace"
    func: Callable = cleanup_whitespace
    # args: Optional[CleanupWhitespaceArgs]
    

##

def prepend_prefix(user_input: str, prefix: str) -> str:
    """
    Prepend a given prefix to the user's input.

    Args:
        user_input (str): The original user input.
        prefix (str): The prefix to be prepended.

    Returns:
        str: User input with the prefix prepended.
    """
    return prefix + user_input

class PrependPrefixArgs(InputTransformerArgs):
    prefix: str

class PrependPrefixTransformer(InputTransformer):
    name: str = "prepend_prefix"
    func: Callable = prepend_prefix
    args: PrependPrefixArgs
    

##

def append_suffix(user_input: str, suffix: str) -> str:
    """
    Append a given suffix to the user's input.

    Args:
        user_input (str): The original user input.
        suffix (str): The suffix to be appended.

    Returns:
        str: User input with the suffix appended.
    """
    return user_input + suffix

class AppendSuffixArgs(InputTransformerArgs):
    suffix: str
    
class AppendSuffixTransformer(InputTransformer):
    name: str = "append_suffix"
    func: Callable = append_suffix
    args: AppendSuffixArgs

##


# Transformation dictionary.
INPUT_TRANSFORMERS: Dict[str, InputTransformer] = {
    'cleanup_whitespace': CleanupWhitespaceTransformer,
    'prepend_prefix': PrependPrefixTransformer,
    'append_suffix': AppendSuffixTransformer
}

def cast_to_transformer_obj(transformer: Union[Dict[str, Any], InputTransformer]) -> InputTransformer:
    """
    Convert the given transformation to an InputTransformer object.

    Args:
        transformer (Union[Dict[str, Any], InputTransformer]): 
            A dictionary representation or an InputTransformer object.

    Returns:
        InputTransformer: The resulting InputTransformer object.
    """
    if isinstance(transformer, InputTransformer):
        return transformer
    
    transformer_name = transformer.get("name")
    
    if transformer_name not in INPUT_TRANSFORMERS:
        raise ValueError(f"Unknown transformer: {transformer_name}")
    transformer_class = INPUT_TRANSFORMERS[transformer_name]
    
    # Prepare the data to be passed to InputTransformer
    transformer_init_data = {
        "name": transformer_name,
        "func": transformer_class.__fields__["func"].default
    }
    
    # Validate 'args' based on the associated args dict if it exists.
    if "args" in transformer_class.__fields__:
        args_class = transformer_class.__fields__["args"].annotation
        args_data = transformer.get("args", {})  # dict args if it exists
        transformer_init_data["args"] = args_class(**args_data)  # This will raise a validation error if args are incorrect.

    return transformer_class(**transformer_init_data)

def transform_input(user_input: str, transformations: List[InputTransformer]) -> str:
    """
    Apply a sequence of transformations to the user's input.

    Args:
        user_input (str): The original user input.
        transformations (List[InputTransformer]): 
            A list of InputTransformer objects to apply.

    Returns:
        str: Transformed user input.
    """
    for transformer in transformations:
        # Grab the function
        transformer_func = transformer.func

        # Grab the "args" if it exists, otherwise empty dict
        try:  # simpler than checking if class has args
            transformer_args = transformer.args.model_dump()
        except AttributeError:
            transformer_args = {}

        user_input = transformer_func(user_input, **transformer_args)
        logger.info(f"Applying transformation {transformer.name} with arguments {transformer_args}")

    return user_input

if __name__ == "__main__":
    user_input = input("Enter a string: ")
    transformations = [
        {
            "name": "cleanup_whitespace"
        },
        {
            "name": "prepend_prefix", 
            "args": {"prefix": "PREFIX - "}
        },
        {
            "name": "append_suffix", 
            "args": {"suffix": " - SUFFIX"}
        }
    ]
    transformed_input = transform_input(user_input, transformations)
    print(f"Transformed input: {transformed_input}")
