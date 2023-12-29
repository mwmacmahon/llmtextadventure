## Unimplemented system for running the engine as a server.
## This would allow for multiple users to interact with the same engine,
## and either bring their own save data or load from something
## on the server side. The system would maintain a dictionary of
## session IDs and ConversationEngine subclass instances, and would have
## an endpoint for creating a new engine, and an endpoint for each
## exposed method of ConversationEngine, so that the user can
## interact with the remote engine via HTTP requests almost identically
## to how they would interact with a local engine.

## Note - should create a ClientEngine subclass of ConversationEngine
## that has the same interface as ConversationEngine, but instead of
## calling the LLM service, it calls the server's exposed methods.

from fastapi import FastAPI, HTTPException, Body
from typing import Dict, Optional
from modules.core.engine import ConversationEngine, Config, State
from modules.utils import load_yaml, save_yaml

app = FastAPI()
engines: Dict[str, ConversationEngine] = {}

@app.post("/create_engine/{session_id}")
async def create_engine(
    session_id: str, 
    save_path: Optional[str] = None, 
    config_data: Optional[Dict] = Body(default=None), 
    state_data: Optional[Dict] = Body(default=None)
):
    """
    Creates a new ConversationEngine instance for a given session ID.
    Users can either provide a path to a saved state or send config and state data directly.

    Args:
        session_id (str): Unique identifier for the user's session.
        save_path (Optional[str]): Path to a saved state file.
        config_data (Optional[Dict]): Configuration data for the engine.
        state_data (Optional[Dict]): State data for the engine.

    Returns:
        Dict: Confirmation message on successful creation.
    """
    if session_id in engines:
        raise HTTPException(status_code=400, detail="Engine already exists for this session.")

    # Load from save_path if provided
    if save_path:
        loaded_data = load_yaml(save_path)
        config_data = loaded_data.get("config")
        state_data = loaded_data.get("state")
    
    # Create new engine
    engine = ConversationEngine(config_data=config_data, state_data=state_data)
    engines[session_id] = engine
    return {"message": "Engine created successfully"}

@app.post("/query/{session_id}")
async def query(session_id: str, user_input: str):
    """
    Processes user input for a given session ID's ConversationEngine instance.

    Args:
        session_id (str): Unique identifier for the user's session.
        user_input (str): The user's input text to be processed.

    Returns:
        Dict: Processed response from the engine.
    """
    if session_id not in engines:
        raise HTTPException(status_code=404, detail="Engine not found for this session.")
    return await engines[session_id].process_input(user_input)

@app.get("/save_state/{session_id}")
async def save_state(session_id: str, output_path: str):
    """
    Saves the current state of a given session ID's ConversationEngine instance.

    Args:
        session_id (str): Unique identifier for the user's session.
        output_path (str): Path to save the engine's current state.

    Returns:
        Dict: Confirmation message on successful saving.
    """
    if session_id not in engines:
        raise HTTPException(status_code=404, detail="Engine not found for this session.")
    state = engines[session_id].state
    save_yaml(state, output_path)
    return {"message": "State saved successfully"}

# Other endpoints as necessary

