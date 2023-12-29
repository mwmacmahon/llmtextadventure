

from typing import Type, TypeVar, Optional, Union, Any, Dict, get_args, get_origin
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
import yaml


# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# T is a type variable that can be any subclass of BaseConfig.
# This allows us to use T to denote the specific subclass that is being used.
T = TypeVar('T', bound='BaseConfig')


class BaseConfig(BaseModel):
    """
    Base class for configuration management. 
    This class is designed to be subclassed for specific configurations.
    It provides methods to create a configuration instance based on a yaml schema.
    Do NOT use any parameters whose names start with "model_" or it will cause errors

    Attributes:
        None (must be subclassed)
    """

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """
        Method to get the path of the yaml schema file.
        Must be implemented in each subclass.

        Returns:
            str: Path to the yaml schema file.
        """
        raise NotImplementedError("This method should be overridden in subclasses")

    @classmethod
    def create(cls: Type[T], **data) -> T:
        """
        Create an instance of a configuration class based on a yaml schema.
        The method loads the schema and fills in any missing values with defaults.

        Args:
            cls (Type[T]): The class for which an instance is to be created.
            **data: Arbitrary keyword arguments that represent the configuration values.

        Returns:
            T: An instance of the class (or subclass) with the configuration loaded.
        
        Raises:
            ValidationError: If the provided data does not conform to the schema.
        """
        schema_path = cls.get_schema_path()
        try:
            with open(schema_path, 'r') as file:
                schema = yaml.safe_load(file)
        except FileNotFoundError as e:
            logger.error(f"Failed to find schema file {schema_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load schema file {schema_path}: {e}")
            raise

        # Make sure this schema is actually valid and matches the code
        cls.ensure_all_fields_present_in_schema(schema, cls)
        cls.validate_schema_with_class(schema, cls) 


        # print(f"data: {data}")
        schema_properties = schema[cls.__name__]['properties']
        for key, value in schema_properties.items():
            # print(f"key: {key}, value: {value}")
            if key not in data and 'default' in value:
                data[key] = value['default']
        # print(f"data: {data}")

        try:
            return cls(**data)
        except ValidationError as e:
            logger.error(f"Error creating {cls.__name__}: {e}")
            raise

    @classmethod
    def ensure_all_fields_present_in_schema(cls, schema: Dict, config_class: Type[BaseModel]):
        """
        Ensures that all fields defined in the configuration class are present in the schema,
        along with their required status and type.

        Args:
            config_class (Type[BaseModel]): The configuration class to check.
            schema_properties (Dict[str, Any]): Properties from the schema file.

        Raises:
            ValueError: If a field in the class is missing from the schema, or if required/type attributes are missing.
        """
        schema_properties = schema[cls.__name__]['properties']
        for field_name, field in config_class.model_fields.items():
            if field_name not in schema_properties:
                raise ValueError(f"Field '{field_name}' in {config_class.__name__} is missing from the schema")

            # Check for the presence of 'required' and 'type' attributes in the schema
            # The actual validation of whether they match will be in validate_schema_with_class()
            schema_field = schema_properties[field_name]
            if 'required' not in schema_field:
                raise ValueError(f"'required' attribute for field '{field_name}' is missing in the schema for {config_class.__name__}")

            if 'type' not in schema_field:
                raise ValueError(f"'type' attribute for field '{field_name}' is missing in the schema for {config_class.__name__}")

    @classmethod
    def validate_schema_with_class(cls, schema: Dict[str, Any], config_class: Type[BaseModel]):
        """
        Validates that the schema properties match the class attribute definitions,
        including checks for type correctness even for optional fields.

        Args:
            schema_properties (Dict[str, Any]): Properties from the schema file.
            config_class (Type[BaseModel]): The configuration class to validate against.

        Raises:
            ValueError: If there is a mismatch between the schema and class definitions.
        """
        schema_properties = schema[cls.__name__]['properties']
        for attr_name, attr_field in config_class.model_fields.items():
            if attr_name not in schema_properties:
                raise ValueError(f"Attribute '{attr_name}' not found in schema for {config_class.__name__}")

            schema_attr = schema_properties[attr_name]
            # Validate type even if the field is optional and not in data
            if 'type' in schema_attr:
                schema_type = schema_attr['type']
                if not cls.is_type_match(schema_type, attr_field.annotation):
                    raise ValueError(f"Type mismatch for '{attr_name}' in {config_class.__name__}")

            # Validate required status
            if 'required' in schema_attr and not attr_field.is_required() == schema_attr['required']:
                raise ValueError(f"Required status mismatch for '{attr_name}' in {config_class.__name__}")

    @staticmethod
    def is_type_match(schema_type: str, python_type: Type) -> bool:
        """
        Dynamically checks if the schema type matches the Python type,
        considering complex types like Union.

        Args:
            schema_type (str): The type from the schema.
            python_type (Type): The Python type to check against.

        Returns:
            bool: True if types match, False otherwise.
        """
        type_mapping = {
            'string': str,
            'integer': int,
            'int': int,
            'float': float,
            'object': (dict, BaseModel),  # 'object' in schema is a generic catch-all type
            # Additional mappings can be added here
        }

        # Handling Union types (e.g., Union[int, None])
        if get_origin(python_type) is Union:
            inner_types = get_args(python_type)

            # Special handling for Optional types (Union[T, NoneType])
            if NoneType in inner_types:
                # Filter out NoneType and check if remaining type matches
                non_none_types = [t for t in inner_types if t is not NoneType]
                return any(BaseConfig.is_type_match(schema_type, t) for t in non_none_types)

            # All inner types must match the schema type
            return all(BaseConfig.is_type_match(schema_type, t) for t in inner_types)

        # Special handling for dict type
        if schema_type in ['dict', 'object'] and (python_type == Dict or get_origin(python_type) == Dict):
            return True

        # Handling direct type matches and subclasses
        expected_python_type = type_mapping.get(schema_type, object)
        return isinstance(python_type, expected_python_type) or issubclass(python_type, expected_python_type)


    @model_validator(mode='before')  # acts on raw input dict
    @classmethod
    def validate_fields(cls, data):
        """
        Validate the entire input data based on the yaml schema.
        Can also do @field_validator in subclasses 
        to check individual fields to arbitrary precision

        Note: every type of check in the schema must be implemented here!

        Args:
            data: The data to validate.

        Returns:
            dict: The validated data.
        """

        schema_path = cls.get_schema_path()

        with open(schema_path, 'r') as file:
            schema = yaml.safe_load(file)

        schema_properties = schema[cls.__name__]['properties']

        # Validate every item in the schema
        for field_name, field_info in schema_properties.items():
            if field_name in data:
                value = data[field_name]
                # Apply minimum and maximum validation if they exist in the schema
                if 'minimum' in field_info and value < field_info['minimum']:
                    raise ValueError(f'{field_name} must be at least {field_info["minimum"]}')
                if 'maximum' in field_info and value > field_info['maximum']:
                    raise ValueError(f'{field_name} must be no more than {field_info["maximum"]}')
                # 
                if 'enum' in field_info:
                    enum_values = field_info['enum']
                    if value not in enum_values:
                        raise ValueError(f'{field_name} must be one of {enum_values}')
        
        return data
    

    # # Can use specific validators in addition to the schema
    # # checking provided by the BaseConfig class.
    # @field_validator('backend_model_settings', mode='before')
    # def validate_backend_model_settings(cls, value):
    #     if isinstance(value, dict):
    #         if 'model' not in value:
    #             raise ValueError("backend_model_settings must contain a 'model' key")
    #         return value
    #     else:
    #         raise ValueError("backend_model_settings must be a dictionary")



##### FOR LLM MODULE #####

# from pydantic import BaseModel, ValidationError, model_validator, field_validator
# Import BaseConfig from config.py
from modules.core.config import BaseConfig


class BackendConfig(BaseConfig):
    """
    Base configuration class for Language Model (LLM) backend settings and parameters.
    Needs to be subclassed for each specific backend.
    Inherits from BaseConfig and defines specific fields relevant to LLM Backend.
    Do NOT use any attributes whose names start with "model_" or it will cause errors

    Attributes:
        name_of_model (str): Name of the model to use.
    """


    ## DON'T do this here, this class is meant to be subclassed
    # @classmethod
    # def get_schema_path(cls) -> str:
    #     """Provides the path to the yaml schema for BackendConfig."""
    #     return "./config/schemas/backendconfig-base.yml"


class OpenABackendConfig(BackendConfig):
    """
    
    Inherits from BaseConfig and defines specific fields relevant to LLM Backend.
    Do NOT use any attributes whose names start with "model_" or it will cause errors

    Attributes:
        name_of_model (str): Name of the model to use.
        backend_model_settings (dict): Settings unique to OpenAI (placeholder)
    """

    name_of_model: str
    backend_model_settings: dict

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for BackendConfig."""
        return "./config/schemas/backendconfig-openai.yml"


class HFTGIBackendConfig(BackendConfig):
    """
    
    Inherits from BaseConfig and defines specific fields relevant to LLM Backend.
    Do NOT use any attributes whose names start with "model_" or it will cause errors

    Attributes:
        name_of_model (str): Name of the model to use.
        backend_model_settings (dict): Settings unique to HFTGI (placeholder)
    """

    name_of_model: str
    backend_model_settings: dict

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for BackendConfig."""
        return "./config/schemas/backendconfig-hftgi.yml"


class OobaboogaBackendConfig(BackendConfig):
    """
    
    Inherits from BaseConfig and defines specific fields relevant to LLM Backend.
    Do NOT use any attributes whose names start with "model_" or it will cause errors

    Attributes:
        name_of_model (str): Name of the model to use.
        backend_model_settings (dict): Settings unique to oobabooga (placeholder)
    """

    name_of_model: str
    backend_model_settings: dict

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for BackendConfig."""
        return "./config/schemas/backendconfig-oobabooga.yml"


class LLMConfig(BaseConfig):
    """
    Configuration class for Language Model (LLM) backend and generation settings 
    and parameters.
    Inherits from BaseConfig and defines specific fields relevant to LLM.
    Do NOT use any attributes whose names start with "model_" or it will cause errors

    Attributes:
        backend_config_type (str): Backend provider for the language model.
        backendConfig (BackendConfig): Model backend config object.
        max_tokens (int): Maximum number of tokens for the model's input.
        temperature (float): Temperature parameter for the model.
        top_p (float): Top-p parameter for the model.
    """

    backend_config_type: str
    backend_config: Optional[BackendConfig] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] =  None

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for LLMConfig."""
        return "./config/schemas/generation/llm_config.yml"


    # In this case we use a model validator to set a default BackendConfig,
    # since the schema itself can't implement the default Config class
    # it sets, and we need to know both the backend_config and backend_config_type params.
    @model_validator(mode='before')
    def set_default_backend_config(cls, data):
        # If the backend_config is not set, try to set it to a default for the backend_config_type
        if "backend_config" not in data or data["backend_config"] is None:
            if data["backend_config_type"] == "OpenAI":
                data["backend_config"] = OpenABackendConfig.create()
                return data
            elif data["backend_config_type"] == "HFTGI":
                data["backend_config"] = HFTGIBackendConfig.create()
                return data
            elif data["backend_config_type"] == "Oobabooga":
                data["backend_config"] = OobaboogaBackendConfig.create()
                return data
            else:
                raise ValueError(f"Unknown backend type {data['backend_config_type']}")
        # Otherwise, look for a string or dict and convert it to an object
        if isinstance(data["backend_config"], str):
            # Interpret the value as a class name and create an instance
            backend_class = globals().get(data["backend_config"], BackendConfig)
            data["backend_config"] = backend_class.create()
            return data
        
        return data







##### FOR STATE MODULE #####

# from pydantic import BaseModel, ValidationError, model_validator, field_validator
# Import BaseConfig from config.py
# from modules.core.config import BaseConfig

class State(BaseConfig):
    """
    Configuration class holding the state of the game, excluding items like the 
    conversation history which are covered by the State configuration class.
    Inherits from BaseConfig and defines specific fields relevant to LLM.
    Do NOT use any attributes whose names start with "model_" or it will cause errors

    Attributes:
        app_name (str): The type of game being played.
    """

    app_name: str

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for State."""
        return "./config/schemas/gamestate.yml"



class State(BaseConfig):
    """
    Configuration class holding the state of the conversation/game.
    Inherits from BaseConfig and defines specific fields relevant to LLM.
    Do NOT use any attributes whose names start with "model_" or it will cause errors

    Attributes:
        history (list): List of messages in the conversation/game,
        llm_io_history (list): List of raw messages with no post-processing
        app_state (State, optional): State object for the game.
    """

    history: list
    llm_io_history: list
    app_state: Optional[State] = None

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for State."""
        return "./config/schemas/state.yml"


# # Example usage
# llm_config = LLMConfig.create(
#     llm_backend="OpenAI",
#     llm_config={"model": "gpt-3.5-turbo"},
#     max_tokens=300
# )
# print(f"llm_config: {llm_config.llm_config}")