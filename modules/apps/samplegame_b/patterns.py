
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type, Any, Dict
from modules.core.config import BaseConfig
from modules.core.patterns import Config, State

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Contains the State, Config, and ConversationEngine classes for Sample Game B

class SampleGameBState(State):
    """
    Manages the dynamic state of the game, adaptable to different scenarios.
    This is for Sample Game B.

    This class serves as a container for all the current state information of the game. 
    It includes time tracking, hidden data about events or triggers, situational flags 
    for specific player actions or game events, resources which can vary based on the game,
    character information, player inventory, the state of the game world, and other 
    miscellaneous data that might be necessary for specific game scenarios.

    Attributes:
        [Inherited from State] history, llm_io_history
        time (str): Current in-game time, formatted as a string.
        hidden_data (dict): Data about upcoming events or triggers that are not directly visible to the player.
        situational_flags (dict): Flags for specific events or player actions that can affect game flow.
        resources (dict): Resource levels, which can vary based on the game's requirements.
        characters (dict): Information about NPCs or player characters including stats, locations, etc.
        inventory (dict): Player's inventory, containing items that the player has collected.
        world_state (dict): Environmental or world-specific data, such as weather, location status, etc.
        other (dict): Additional data as required for extending the game's functionality.
    """
    # [Inherited from State] history, llm_io_history
    time: str
    hidden_data: dict
    situational_flags: dict
    resources: dict
    characters: dict
    inventory: dict
    world_state: dict
    other: dict

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for Sample Game B's state."""
        return "./config/schemas/apps/samplegame-b/default_state.yml"

class SampleGameBConfig(Config):
    """
    Manages the static config of the game, adaptable to different scenarios.
    This is designed to cover the immutable but configurable settings of the app.
    This subclass is for the Sample Game B.

    Attributes:
        [Inherited from Config] interface_type, interface_config, llm_config, transformation_config, parsing_config
        scenario_name (str): Name of the specific game scenario being run.
        difficulty (str): Difficulty level of the game.
    """
    # [Inherited from Config] interface_type, interface_config, llm_config, transformation_config, parsing_config
    scenario_name: str
    difficulty: str
    
    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for Sample Game B's config."""
        return "./config/schemas/apps/samplegame-b/config.yml"