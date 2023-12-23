
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type
from modules.core.config import BaseConfig
# from modules.conversations import \
#     ConversationManager, ChatManager, ConversationManager, \
#         Config, State
from modules.generation.llm_manager import LLMEngine, LLMConfig
from modules.apps.samplegame_a.engine import SampleGameAState, SampleGameAConversationManager
from modules.apps.samplegame_b.engine import SampleGameBState, SampleGameBConversationManager

# Global mappings from conversation types 
# to Managers and (optionally) States
# Left: Conversation Type
# Right: Manager Class / State Class
CONVERSATION_MANAGERS = {
    "Chat": "ChatManager",
    "SampleGameA": "SampleGameAConversationManager",
    "SampleGameB": "SampleGameBConversationManager"
}
GAME_STATES = {
    "SampleGameA": "SampleGameAState",
    "SampleGameB": "SampleGameBState"
}
from modules.utils import load_yaml_config

class ConversationEngine(BaseModel):
    """
    Orchestrates the overall flow of the conversation or game. It manages
    the interaction between various components like ConversationManager and LLMEngine.

    Attributes:
        config (Config): Full configuration for the conversation/game.
        state (State): State of the conversation/game.
        conversation_manager (ConversationManager): Manager controlling the conversation/game flow.
        llm_engine (LLMEngine): Engine for interfacing with the LLM service.
    """

    config: Config
    state: State
    conversation_manager: ConversationManager
    llm_engine: LLMEngine

    def __init__(self, config_path: str):
        """
        Initializes the ConversationEngine with configurations and components.

        Args:
            config_path (str): Path to the configuration file.
        """
        config_data = load_yaml_config(config_path)
        app_name = config_data.get('app_name', 'DefaultApp')

        # Dynamically determine which Config and State classes to use
        ConfigClass = self.get_app_config_class(app_name)
        StateClass = self.get_app_state_class(app_name)

        # Create Config and State instances
        self.config = ConfigClass.create(**config_data)
        self.state = StateClass.create(**config_data)

        # Initialize LLMEngine
        self.llm_engine = LLMEngine(self.config.llm_config)

        # Initialize the appropriate ConversationManager
        ConversationManagerClass = self.get_app_conversation_manager_class(app_name)
        self.conversation_manager = ConversationManagerClass(
            llm_engine=self.llm_engine, 
            config=self.config, 
            state=self.state
        )

    def get_app_config_class(self, app_name: str) -> Type[Config]:
        # Logic to return the correct Config class based on app_name
        pass

    def get_app_state_class(self, app_name: str) -> Type[State]:
        # Logic to return the correct State class based on app_name
        pass

    def get_app_conversation_manager_class(self, app_name: str) -> Type[ConversationManager]:
        # Logic to return the correct ConversationManager subclass based on app_name
        pass

    def run(self):
        """
        Runs the main interaction loop of the conversation or game.
        """
        # Main loop logic
        pass
