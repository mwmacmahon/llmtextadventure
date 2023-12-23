# registry.py
# Mapping of configuration types to their corresponding classes
from modules.apps.chat.engine import ChatConfig, ChatState, ChatManager
from modules.apps.samplegame_a.engine import SampleGameAConfig, SampleGameAState, SampleGameAConversationEngine
from modules.apps.samplegame_b.engine import SampleGameBConfig, SampleGameBState, SampleGameBConversationEngine
from generation.hftgi import HFTGIBackendConfig, HFTGIBackend
from generation.oobabooga import OobaboogaBackendConfig, OobaboogaBackend
from generation.openai import OpenABackendConfig, OpenABackend

APP_CONFIGS = {
    "Chat": ChatConfig,
    "SampleGameA": SampleGameAConfig,
    "SampleGameB": SampleGameBConfig,
}
APP_STATES = {
    "Chat": ChatState,
    "SampleGameA": SampleGameAState,
    "SampleGameB": SampleGameBState,
}
APP_CONVERSATION_MANAGERS = {
    "Chat": ChatManager,
    "SampleGameA": SampleGameAConversationEngine,
    "SampleGameB": SampleGameBConversationEngine,
}

BACKEND_CONFIGS = {
    "OpenAI": OpenABackendConfig,
    "HFTGI": HFTGIBackendConfig,
    "Oobabooga": OobaboogaBackendConfig,
}
BACKENDS = {
    "OpenAI": OpenABackend,
    "HFTGI": HFTGIBackend,
    "Oobabooga": OobaboogaBackend,
}


def get_app_config_class(type: str):
    return APP_CONFIGS.get(type)

def get_app_state_class(type: str):
    return APP_STATES.get(type)

def get_app_conversation_engine_class(type: str):
    return APP_CONVERSATION_MANAGERS.get(type)

def get_backend_config_class(type: str):
    return BACKEND_CONFIGS.get(type)

def get_backend_class(type: str):
    return BACKENDS.get(type)