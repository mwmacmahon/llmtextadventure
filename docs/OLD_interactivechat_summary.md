# Interactive Chat Interface Program Summary

## Program Overview

This program establishes an interactive chat interface that facilitates seamless communication between users and an AI model accessed via the OpenAI API. Using Python and the `asyncio` library for asynchronous operations, the software fetches configuration parameters from a `config.yml` file and sensitive environment variables from a `.env` file.

Each session's interactions between the user and the AI assistant are archived within a JSON file. The chat can be resumed by loading this file during the next session. Asynchronous processes ensure that the application remains responsive, especially during the AI's response times.

## OpenAI API Integration

The OpenAI API provides a seamless interface to interact with powerful generative AI models like GPT-3 and GPT-4. In this program, we've integrated with the API using asynchronous calls to allow real-time conversation with the AI. In the future, we aim to expand the utility of the program by facilitating local model integrations, thereby reducing the dependency on API calls and enhancing performance.

## Asynchronous Approach

The asynchronous approach using Python's `asyncio` library ensures that the application remains responsive, especially during the AI's response times. It allows the main thread to stay free, making other tasks possible without blocking. This structure provides a solid foundation for scaling this application, potentially moving it to a web-based application or even an API service.

## Token Counting, Context Limits, and Truncation

Conversations must remain within the model's acceptable input length:

- **Token Counting**:
  - Each chat item is pre-equipped with its token count (`num_tokens`) to streamline performance.
  - The `count_tokens` function plays a crucial role in this process.

- **Protected Chat Items**:
  - Some chat items might be designated as 'protected', ensuring their significance isn't discarded. Such items are never truncated.
  - Maximum configured output tokens from the AI's responses also count towards the context limit.
  - Starting from the latest message, the software works in reverse. If the total token count surpasses the model's context limit, the responsible message and all prior ones are flagged as truncated.
  - The function `truncate_chat_history` is instrumental for this mechanism.

- **Passing Chat History**:
  - When channeling chat history to `custom_streaming_chat`, items flagged as "truncated":True are left out unless they are also designated "protected":True.

## To-Do List

- [ ] Work out existing bugs/functionality.
  
- [ ] Add user input transformation script.
  
- [ ] Add shell of auto-chat feature (AI talking to AI).

## Appendix

### FILE: main.py

**Imports**:
- `asyncio`
- `os`
- `json`
- `argparse`
- `logging`
- `datetime`
- `dotenv`
- `streamingapi.custom_streaming_chat`
- `streamingapi.count_tokens`
- `chat_helpers.get_filepath`
- `chat_helpers.display_chat_history`
- `chat_helpers.truncate_chat_history`
- `chat_helpers.load_config`

**Functions**:
- `interactive_session()`: This asynchronous function manages the user interactions, processes AI responses, and saves chat histories.
    - **EXAMPLE**: 
      - **Input**: api_key="YOUR_API_KEY", chat_history=[], config={}
      - **Output**: Engages the user in an interactive chat, saving history periodically.

### FILE: chat_helpers.py

**Imports**:
- `json`
- `yaml`
- `datetime`
- `streamingapi.count_tokens`
- `typing.List`
- `typing.Dict`

**Functions**:
- `get_filepath()`: This function retrieves the filepath based on user input, default values, or a combination of both.
    - **Parameters**: 
      - args_value: Command line argument for filename.
      - prompt: Prompt displayed to ask user for filename.
      - default_value: Default filename if user provides none (optional).
      - extension: Expected file extension (default is .json).
    - **Returns**: str: Full filepath.
    - **EXAMPLE**:
      - **Input**: args_value=None, prompt="Enter filename: ", default_value="chat", extension=".json"
      - **Output**: Either uses user's inputted filename, default filename "chat.json", or generates one based on input + extension.
- `display_chat_history()`: This function renders the chat history to the console as if it had taken place in real-time.
    - **Parameters**: 
      - chat_history: List of chat interactions, where each interaction contains the 'role' (system, user, assistant) and 'content' (the message).
- `truncate_chat_history()`: This function trims the chat history based on token limits. It ensures that the total token count (including expected response tokens) doesn't surpass the context limit.
    - **Parameters**: 
      - chat_history: Chat interactions that might be truncated.
      - context_limit: Maximum number of tokens allowed in the chat context.
      - max_tokens: Maximum number of tokens for the assistant's response.
    - **Returns**: list: Potentially truncated chat history.

### FILE: streamingapi.py

`streamingapi.py` is designed to interact with the OpenAI API in real-time using streaming functionality. This allows the application to provide immediate feedback to the user from the AI model. The file offers utility functions to count tokens in user input and launch a custom chat that interfaces with the GPT models provided by OpenAI.

**Essential Functions & Components**:

1. `count_tokens_openai_api(text: str) -> int`
    - **Purpose**: Count tokens in a text using the OpenAI API.
    - **Parameters**: text: The text string to count tokens for.
    - **Returns**: The number of tokens in the text.
2. `count_tokens_tiktoken(text: str, encoding_name: str = "cl100k_base") -> int`
    - **Purpose**: Utilize the tiktoken method to count the number of tokens in a text.
    - **Parameters**: text: Text string for token counting. encoding_name: Encoding name used with tiktoken.
    - **Returns**: The number of tokens in the text.
3. `count_tokens(text: str) -> int`
    - **Purpose**: Wrapper function to count tokens in text.
    - **Parameters**: text: The text string to count tokens for.
    - **Returns**: Token count in the provided text.
4. `custom_streaming_chat(...)`
    - **Purpose**: Launches a custom streaming chat with OpenAI GPT models, providing real-time responses.
    - **Parameters**: api_key: The API key for OpenAI. query: The user's message to send to the chat model. config_dict: Dictionary containing model configurations. chat_history: Existing chat history for context. logger: Logger object for logging messages.
    - **Yields**: Model's real-time response chunks and the final response as a dictionary.

**Additional Notes**:
- The file employs both the OpenAI API and tiktoken library to count tokens, offering flexibility in how token counts are calculated.
- By using the streaming feature of the OpenAI API, the `custom_streaming_chat` function gives real-time feedback to users, thus enhancing user experience.
- Robust error handling mechanisms are in place, making the module more reliable and fault-tolerant. This is especially crucial for real-time applications like chat interfaces or web-based platforms.
