
## NOTE: this doesn't work yet, very very tbd

import asyncio
import json
import llmtextadventure.modules.interactive_cli_session as interactive_cli_session  # Assuming main.py is in the same directory

SWITCH_ROLES_PROMPT = "Now please switch roles and tell me what the next item I will say in this conversation will be"
MAX_ITERATIONS = 4  # Define the number of chat iterations before ending


def simulated_input_provider(prompt: str, next_input: str) -> str:
    """
    Simulated input provider for interactive chat.

    :param prompt: The prompt string (ignored in this context)
    :param next_input: The next input to be fed into the chat session
    :return: The next input string
    """
    print(prompt + next_input)
    return next_input


async def auto_chat_session(api_key: str, chat_history_user: list, chat_history_assistant: list, config: dict):
    """
    Run an automated chat session using two simultaneous chats.

    :param api_key: OpenAI API key
    :param chat_history_user: Initial chat history for the "user" chat session
    :param chat_history_assistant: Initial chat history for the "assistant" chat session
    :param config: Configuration dictionary
    """
    next_input = SWITCH_ROLES_PROMPT  # Initialize with the switch roles prompt

    for _ in range(MAX_ITERATIONS):
        # Simulate user chat
        await interactive_cli_session.interactive_session(
            api_key, 
            chat_history_user, 
            config, 
            lambda prompt: simulated_input_provider(prompt, next_input)
        )
        
        # Get the latest response from the "user" chat and set it as the next input for the "assistant" chat
        next_input = chat_history_user[-1]["content"]

        # Simulate assistant chat
        await interactive_cli_session.interactive_session(
            api_key, 
            chat_history_assistant, 
            config, 
            lambda prompt: simulated_input_provider(prompt, next_input)
        )

        # Get the latest response from the "assistant" chat and set it as the next input for the "user" chat
        next_input = chat_history_assistant[-1]["content"]

        # Add a check to exit if the conversation has reached a natural conclusion
        # This is a basic check and can be enhanced further based on specific use cases
        if next_input.lower() in ["goodbye", "bye", "exit", "end"]:
            break

    # Save the final chat histories (optional)
    with open("auto_chat_user.json", 'w') as f:
        json.dump({"conversation": chat_history_user, "configuration": config}, f, indent=4)
    with open("auto_chat_assistant.json", 'w') as f:
        json.dump({"conversation": chat_history_assistant, "configuration": config}, f, indent=4)


if __name__ == "__main__":
    api_key = interactive_cli_session.os.getenv("OPENAI_API_KEY")
    config = interactive_cli_session.load_config()  # Load the configuration from main.py

    initial_chat_history_user = []
    initial_chat_history_assistant = []

    asyncio.run(auto_chat_session(api_key, initial_chat_history_user, initial_chat_history_assistant, config))
