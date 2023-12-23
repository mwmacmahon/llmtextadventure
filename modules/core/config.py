
from typing import Type, TypeVar, Optional, Union, Any, Dict, get_args, get_origin, get_type_hints, ClassVar
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
import yaml
import inspect
import importlib


# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# T is a type variable that can be any subclass of BaseConfig.
# This allows us to use T to denote the specific subclass that is being used.
T = TypeVar('T', bound='BaseConfig')


## NOTES:
# 1. Initial Configuration Creation:
#   When you create the top-level Config using Config.create(data_dict_from_config_file),
#   the method processes the provided data according to the schema defined in 
#   ./config/schemas/config.yml.
#   This schema includes the definitions for llm_config, transformation_config, parsing_config, 
#   and any other fields like config_name.
# 2. Default Value Augmentation:
#   The .create() method augments the data with default values for any top-level fields 
#   not explicitly set in the input configuration, as long as defaults are specified 
#   in the schema.
# 3. Recursive Creation of Nested Configurations:
#   The method then recursively creates instances of nested BaseConfig subclasses (like 
#   LLMConfig), passing the relevant subset of data for each subclass.
#   Additionally, the entire parent_data (containing top-level parameters) is passed 
#   to these nested configurations to provide context for schema path determination.
# 4. Dynamic Schema Path Determination:
#   Each subclass, such as BackendConfig, uses get_schema_path(data, parent_data) to 
#   dynamically determine its schema based on the provided data and parent_data. For 
#   example, BackendConfig can decide its schema path based on backend_config_type present in parent_data.
# 5. Key Points in Recursive Creation:
#   The data for a nested configuration only includes the relevant part 
#   for that specific configuration.
#   The parent_data provides additional context from the parent configuration, 
#   crucial for determining the correct schema in cases like different backend types.
# 6. Validation and Completion:
#   Once all nested configurations are created, the top-level Config instance is finalized 
#   and validated against the schema. This step ensures all required parameters are present, 
#   either from defaults or explicitly provided in the configuration file.


class BaseConfig(BaseModel):
    """
    Base class for configuration management. 
    This class is designed to be subclassed for specific configurations.
    It provides methods to create a configuration instance based on a yaml schema.
    Do NOT use any parameters whose names start with "model_" or it will cause errors

    Attributes:
        None (must be subclassed)
    """
    _schema_path: ClassVar[Optional[str]] = None


    def to_dict(self, obj=None, seen=None):
        """
        Recursively converts an object to a dictionary. 
        If the object is a `BaseConfig`, calls `.model_dump()` on it. 
        If it's a dictionary, iterates through its values, applying the same logic.
        """
        if seen is None:
            seen = set()

        if obj is None:
            obj = self

        # Circular reference check
        if id(obj) in seen:
            return
        seen.add(id(obj))


        if isinstance(obj, BaseConfig):
            obj_dict = obj.model_dump()
            # Explicitly process each attribute
            for attr_name, attr_value in obj.__dict__.items():
                if isinstance(attr_value, BaseConfig):
                    obj_dict[attr_name] = self.to_dict(attr_value, seen)
                else:
                    obj_dict[attr_name] = attr_value


            # Process additional fields from schema
            schema_properties = obj._schema.get(obj.__class__.__name__, {}).get('properties', {})
            for key in schema_properties:
                if key not in obj_dict:
                    obj_dict[key] = getattr(obj, key, None)

            return obj_dict
            # # This just seems to make everything return null
            # return {key: self.to_dict(value, seen) for key, value in obj_dict.items()}
        elif isinstance(obj, dict):
            return {key: self.to_dict(value, seen) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self.to_dict(item, seen) for item in obj]
        else:
            return obj


    def to_yaml(self) -> str:
        """
        Converts the entire configuration to a YAML-formatted string, including nested configurations.

        Returns:
            str: YAML-formatted string representing the configuration.
        """
        data = self.to_dict()
        return yaml.dump(data, default_flow_style=False)

    def print_yaml(self):
        """
        Prints the entire configuration to the console in YAML format.
        """
        print(self.to_yaml())

    def save_yaml(self, file_path: str):
        """
        Saves the entire configuration to a file in YAML format.

        Args:
            file_path (str): The file path where the YAML should be saved.
        """
        with open(file_path, 'w') as file:
            yaml.dump(self.to_dict(), file, default_flow_style=False)

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
        return cls

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """
        Determine the path of the yaml schema file dynamically based on the provided data.

        Args:
            data (dict, optional): Overriding attribute values for this class.
            parent_data (dict, optional: the final non-object attributes of the parent configuration.

        Returns:
            str: Path to the yaml schema file.
        """
        raise NotImplementedError("This method should be overridden in subclasses")

    @classmethod
    def create(cls: Type[T], data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> T:
        """
        Create an instance of a configuration class based on a yaml schema.
        This method also handles the creation of nested BaseConfig instances.

        Args:
            cls (Type[T]): The class for which an instance is to be created.
            data (dict, optional): Overriding attribute values for this class.
            parent_data (dict, optional: the final attributes of the parent configuration.

        Returns:
            T: An instance of the class with the configuration loaded.
        """

        # Determine the new class and schema path dynamically based on data
        new_cls = cls.get_class(data, parent_data)
        # Get the schema to use for this class
        schema_path = new_cls.get_schema_path(data, parent_data)


        logger.debug("***CLASS CREATION DEBUG INFO***")
        logger.debug(f"This class: {cls}")
        logger.debug(f"data: {data}")
        logger.debug(f"parent data: {parent_data}")
        logger.debug(f"new class: {new_cls}")
        logger.debug(f"schema path: {schema_path}")
        logger.debug("***END CLASS CREATION DEBUG INFO***")


        # Initialize data if not provided
        if data is None:
            data = {}
        
        # Load the schema file
        try:
            with open(schema_path, 'r') as file:
                schema = yaml.safe_load(file)
                new_cls._schema = schema
        except FileNotFoundError as e:
            logger.error(f"Failed to find schema file {schema_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load schema file {schema_path}: {e}")
            raise

        if new_cls.__name__ not in schema:
            raise ValueError(f"Schema for {new_cls.__name__} not found in {schema_path}")

        # Make sure this schema is actually valid and matches the code
        new_cls.ensure_all_fields_present_in_schema(schema, new_cls)
        new_cls.validate_schema_with_class(schema, new_cls) 

        # Load defaults from schema into data
        schema_properties = schema[new_cls.__name__]['properties']
        for key, value in schema_properties.items():
            # logger.debug(f"key: {key}, value: {value}")
            if key not in data and 'default' in value:
                data[key] = value['default']
        logger.debug(f"data: {data}")

    
        # Merge annotations from all base classes with those of the current class.
        # This ensures we have a complete set of annotations for all fields
        # defined in both the base class and the subclass.
        merged_annotations = {}
        for base in reversed(new_cls.__mro__):
            # Get type hints (annotations) for each class in the Method Resolution Order (MRO)
            # and update the merged_annotations dictionary with these annotations.
            merged_annotations.update(get_type_hints(base))


        # Recursively create nested configurations
        # logger.debug("---------------")
        # logger.debug(data)
        # logger.debug("---")
        # logger.debug(merged_annotations.items())
        # logger.debug("---------------")
        for field, field_type in merged_annotations.items():
            if inspect.isclass(field_type) and issubclass(field_type, BaseConfig):
                logger.debug(f"{field} of type {field_type} is a sublass of BaseConfig, we must .create() it")
                field_data = data.get(field, {})
                field_parent_data = data
                field_config = field_type.create(field_data, field_parent_data)
                data[field] = field_config
                # logger.debug("---------")
            else:
                logger.debug(f"{field} of type {field_type} is not an object")

        try:
            logger.debug(f"Final data: {data}")
            created_class = new_cls(**data)
            logger.debug(f"Created class: {created_class}")
            return created_class
        except ValidationError as e:
            logger.error(f"Error creating {new_cls.__name__}: {e}")
            raise

    @classmethod
    def ensure_all_fields_present_in_schema(cls, schema: Dict, config_class: Type[BaseModel]):
        """
        Ensures that all fields defined in the configuration class are present in the schema,
        along with their required status and type. Note that this is one-way - the schema
        may contain fields that are not defined in the class, but not vice versa.

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

        # # Now check that all fields in the schema are present in the class - NOTE: we don't do this anymore
        # for field_name, field in schema_properties.items():
        #     if field_name not in config_class.model_fields:
        #         raise ValueError(f"Field '{field_name}' in the schema for {config_class.__name__} is missing from the class")

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


    @classmethod
    @model_validator(mode='before')
    def validate_fields(cls, data):
        """
        Validate the entire input data based on the yaml schema.
        We do this manually rather than as a @field_validator because
        we need the schema from create() to validate the entire data.

        Note: every type of check in the schema must be implemented here!

        Args:
            schema: The yaml schema.
            data: The data to validate.

        Returns:
            Nothing, but raises a ValueError if validation fails.
        """

        schema = cls._schema
        schema_properties = schema[cls.__name__]['properties']


        # Merge annotations from all base classes with those of the current class.
        # This ensures we have a complete set of annotations for all fields
        # defined in both the base class and the subclass.
        merged_annotations = {}
        for base in reversed(cls.__mro__):
            # Get type hints (annotations) for each class in the Method Resolution Order (MRO)
            # and update the merged_annotations dictionary with these annotations.
            merged_annotations.update(get_type_hints(base))


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
            else:
                # Field is missing in data! Check if the field is required
                if field_info['required']:
                    # Yes - so see if this field is an object/class.
                    logger.debug(f"Missing required field {field_name} - testing if object")
                    logger.debug(merged_annotations)
                    if field_name in merged_annotations:
                        if issubclass(merged_annotations[field_name], BaseConfig):
                            continue  # if so, continue loop and move on
                        # No - so raise an error
                        raise ValueError(f'{field_name} is required')
                    else:
                        logger.debug(f"No annotation for {field_name}")
        
        return data


    # # Can use specific validators in addition to the schema
    # # checking provided by the BaseConfig class.
    # @field_validator('openai_settings', mode='before')
    # def validate_openai_settings(cls, value):
    #     if isinstance(value, dict):
    #         if 'model' not in value:
    #             raise ValueError("openai_settings must contain a 'model' key")
    #         return value
    #     else:
    #         raise ValueError("openai_settings must be a dictionary")

