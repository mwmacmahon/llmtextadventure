
from typing import Type, TypeVar, Optional, Union, List, Any, Dict, get_args, get_origin, get_type_hints, ClassVar
from types import NoneType
from pydantic import BaseModel, ValidationError, model_validator, field_validator
import yaml
import inspect
import importlib

from modules.interfaces.patterns import Interface, InterfaceConfig


class WebInterfaceConfig(InterfaceConfig):
    """"""
    interface_mode: str

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for HFTGIBackendConfig."""
        return "./config/schemas/interfaces/webui.yml"


class WebInterface(Interface):
    """
    Web specific Interface implementation.

    Attributes:
        interface_config (InterfaceConfig): Configuration specific to Web.
    """
    def __init__(self, interface_config):
        super().__init__(interface_config)

    def read_input(self, input_prompt: str = ""):
        raise NotImplementedError

    def write_output(self, message: str, output_prefix: str = ""):
        raise NotImplementedError
    
    def display_chat_history(self, chat_history: List[Dict[str, str]]):
        raise NotImplementedError
    