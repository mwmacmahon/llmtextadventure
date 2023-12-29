
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type
from modules.core.config import BaseConfig
from modules.core.patterns import Config, State
from modules.core.engine import ConversationEngine
from modules.apps.chat.engine import ChatState, ChatEngine
from modules.apps.samplegame_a.engine import SampleGameAState, SampleGameAEngine
from modules.apps.samplegame_b.engine import SampleGameBState, SampleGameBEngine
from modules.utils import load_yaml, load_json
from modules.interfaces.patterns import Interface, INTERFACE_CLASSES
from modules.interfaces.cli import CLIInterface
from modules.interfaces.webui import WebInterface
import os

# All possible interface classes must be imported here
from modules.interfaces.api import APIInterface
from modules.interfaces.cli import CLIInterface
from modules.interfaces.webui import WebInterface

# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_INTERFACE_TYPE = "cli"
GAME_STATES = {
    "chat": ChatState,
    "samplegamea": SampleGameAState,
    "samplegameb": SampleGameBState
}
ENGINES = {
    "chat": ChatEngine,
    "samplegamea": SampleGameAEngine,
    "samplegameb": SampleGameBEngine
}
INTERFACES = {
    "cli": CLIInterface,
    "webui": WebInterface
}
from modules.utils import load_yaml, load_json

def run_local(app_name: str = None, interface_type: str = None, input_path: str = None, output_path: str = None) -> Type[ConversationEngine]:

    if not app_name and not input_path:
        raise ValueError("Must specify at least one of the following to load_engine(): app_name, input_path")
    
    if input_path:
        if input_path.endswith(".json"):
            input_data = load_json(input_path)
        elif input_path.endswith(".yml"):
            input_data = load_yaml(input_path)
        else:
            raise ValueError(f"Invalid input file type: {input_path}. Valid values are .json and .yml")
    else:
        input_data = {}
        if app_name:
            if "app_name" in input_data:
                if input_data["app_name"] != app_name:
                    raise ValueError(f"app_name specified in input file ({input_data['app_name']}) does not match app_name specified in load_engine() ({app_name})")
            else:
                input_data["app_name"] = app_name  # Add app_name to input_data
        else:
            if "app_name" not in input_data:
                raise ValueError("User must specify app_name manually in load_engine() if input file does not")
            app_name = input_data.get["app_name"]

    if app_name not in GAME_STATES:
        raise ValueError(f"Invalid app type: {app_name}. Valid values are {GAME_STATES.keys()}")
    input_data["config"]["app_name"] = app_name  # Add app_name to config
    
    if interface_type in input_data:
        if interface_type is None:
            interface_type = input_data["interface_type"]
        else:
            input_data["interface_type"] = interface_type  # Update interface_type in input_data
    else:
        if interface_type is None:
            interface_type = DEFAULT_INTERFACE_TYPE
        input_data["interface_type"] = interface_type
    if interface_type not in INTERFACES:
        raise ValueError(f"Invalid interface type: {interface_type}. Valid values are {INTERFACES.keys()}")
    input_data["config"]["interface_type"] = interface_type  # Add interface_type to config
    
    interface_config_data = input_data.get("interface_config", {})
    config_data = input_data.get("config", {})
    state_data = input_data.get("state", {})

    print(f"App type: {app_name}")
    print(f"Interface type: {interface_type}")
    print(f"Config data: {config_data}")
    print(f"State data: {state_data}")
    print(f"Output path: {output_path}")

    # Initialize the appropriate ConversationEngine
    EngineClass = ENGINES[app_name]
    conversation_engine = EngineClass(
        app_name=app_name,
        config_data=config_data, 
        state_data=state_data,
        output_path=output_path
    )
    InterfaceClass = globals()[INTERFACE_CLASSES[interface_type]]
    interface = InterfaceClass(interface_config_data)
    interface.run(conversation_engine)


# if __name__ == "__main__":
#     engine = load_engine("chat", "./testconfig.yml")
#     # engine = load_engine("chat")
#     repr(engine)