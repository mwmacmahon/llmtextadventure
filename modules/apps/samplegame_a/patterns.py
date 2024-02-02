
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type, Any, Dict
from modules.core.config import BaseConfig
from modules.core.patterns import Config, State

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Contains the State, Config, and ConversationEngine classes for Sample Game A

class SampleGameAState(State):
    """
    Manages the dynamic state of the game, adaptable to different scenarios.
    This is for Sample Game A.

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

    # Public data - can be accessed by the user directly or indirectly
    time: str
    situational_flags: list
    resources: list
    inventory: list
    characters: list
    known_events: list
    misc_data: dict

    # Hidden data - cannot be accessed by the user
    hidden_facts: list
    hidden_events: list
    hidden_misc_data: dict

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for Sample Game A's state."""
        return "./config/schemas/apps/samplegame-a/default_state.yml"

class SampleGameAConfig(Config):
    """
    Manages the static config of the game, adaptable to different scenarios.
    This is designed to cover the immutable but configurable settings of the app.
    This subclass is for Sample Game A.
    Attributes:
        [Inherited from Config] interface_type, interface_config, llm_config, transformation_config, parsing_config
        scenario_name (str): Name of the specific game scenario being run.
        difficulty (str): Difficulty level of the game.
    """
    # [Inherited from Config] interface_type, interface_config, llm_config, transformation_config, parsing_config
    scenario_name: str
    universal_first_prompt: str
    universal_post_input_prompt: str
    universal_last_prompt: str
    situational_prompts: list
    misc_options: dict

    @classmethod
    def get_schema_path(cls, data: Optional[Dict[str, Any]] = None, parent_data: Optional[Dict[str, Any]] = None) -> str:
        """Provides the path to the yaml schema for Same Game A's config."""
        return "./config/schemas/apps/samplegame-a/config.yml"
