### config.py   
from typing import Optional
from pydantic import BaseModel, model_validator
import yaml

class BaseConfig(BaseModel):

    @classmethod
    def get_schema_path(cls):
        raise NotImplementedError("This method should be overridden in subclasses")

    @model_validator(mode='before')
    @classmethod
    def validate_fields(cls, data):
        schema_path = cls.get_schema_path()

        with open(schema_path, 'r') as file:
            schema = yaml.safe_load(file)

        schema_properties = schema[cls.__name__]['properties']

        for field_name, field_info in schema_properties.items():
            if field_name in data:
                value = data[field_name]
                # Apply minimum and maximum validation if they exist in the schema
                if 'minimum' in field_info and value < field_info['minimum']:
                    raise ValueError(f'{field_name} must be at least {field_info["minimum"]}')
                if 'maximum' in field_info and value > field_info['maximum']:
                    raise ValueError(f'{field_name} must be no more than {field_info["maximum"]}')
        
        return data
    
    @classmethod
    def create(cls, **data):
        """
        Load LLMConfig using its schema, with the option to override with additional data.

        Args:
            **data: Data to initialize or override the config.

        Returns:
            LLMConfig: The configuration instance.
        """
        schema_path = cls.get_schema_path()
        with open(schema_path, 'r') as file:
            schema = yaml.safe_load(file)

        config_properties = schema[cls.__name__]['properties']
        initial_values = {}

        for key, schema_info in config_properties.items():
            initial_values[key] = data.get(key, schema_info.get('default'))

        return cls(**initial_values)
    
### llmengine.py
# from modules.core.config import BaseConfig

class LLMConfig(BaseConfig):
    """
    Configuration class for Language Model (LLM) settings and parameters.
    """


    llm_backend: str
    model_config: dict
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] =  None

    # Note: use [name]: Optional[some type] = None for optional fields

    @classmethod
    def get_schema_path(cls):
        return "./llm_schema.yml"
    
### 
llm_config = LLMConfig(
    llm_backend="OpenAI",
    model_config={"model": "gpt-3.5-turbo"},
    max_tokens=300
)
