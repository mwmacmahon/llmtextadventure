
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type
from modules.core.config import BaseConfig
from modules.core.patterns import Config, State
from modules.core.engine import ConversationEngine
from modules.apps.chat.engine import ChatState, ChatEngine
from modules.apps.samplegame_a.engine import SampleGameAState, SampleGameAEngine
from modules.apps.samplegame_b.engine import SampleGameBState, SampleGameBEngine
from modules.utils import load_yaml, load_json
import os

# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global mappings from conversation types 
# to Managers and (optionally) States
# Left: App Name
# Right: State Class / Engine Class
GAME_STATES = {
    "Chat": ChatState,
    "SampleGameA": SampleGameAState,
    "SampleGameB": SampleGameBState
}
ENGINES = {
    "Chat": ChatEngine,
    "SampleGameA": SampleGameAEngine,
    "SampleGameB": SampleGameBEngine
}
from modules.utils import load_yaml, load_json

def load_engine(app_name: str = None, input_path: str = None, output_path: str = None) -> Type[ConversationEngine]:

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
    
    config_data = input_data.get("config", {})
    state_data = input_data.get("state", {})

    print(f"App type: {app_name}")
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
    return conversation_engine


# if __name__ == "__main__":
#     engine = load_engine("Chat", "./testconfig.yml")
#     # engine = load_engine("Chat")
#     repr(engine)