import openai
import asyncio
import logging
import tiktoken

openai.util.logger.setLevel(logging.WARNING)

# # doesn't work, the call is wrong or something
# def count_tokens_openai_api(text: str) -> int:
#     """
#     Count the number of tokens in a text string using OpenAI API.

#     Args:
#         text (str): The text string to count tokens for.

#     Returns:
#         int: The number of tokens in the text.
#     """
#     return len(openai.Completion.create(prompt=text, max_tokens=0)["usage"]["total_tokens"])

def count_tokens_tiktoken(text: str, encoding_name: str = "cl100k_base") -> int:
    """
    Count the number of tokens in a text string using tiktoken.

    Args:
        text (str): The text string to count tokens for.
        encoding_name (str): The encoding name to use with tiktoken.

    Returns:
        int: The number of tokens in the text.
    """
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(text))

def count_tokens(text: str) -> int:
    """
    Count the number of tokens in a text string.

    Args:
        text (str): The text string to count tokens for.

    Returns:
        int: The number of tokens in the text.
    """
    # return count_tokens_openai_api(text)
    return count_tokens_tiktoken(text)

async def custom_streaming_chat(api_key: str, query: str, config_dict: dict, chat_history: list, logger: logging.Logger):
    """
    Initiate a custom streaming chat with OpenAI GPT models and yield real-time responses.

    Args:
        api_key (str): The API key for OpenAI.
        query (str): The user query to send to the chat model.
        config_dict (dict): Configuration dictionary containing parameters like model name, max tokens, etc.
        chat_history (list): Previous chat history to provide as context.
        logger (logging.Logger): Logger object to log messages.

    Yields:
        str/dict: Yields model's real-time responses in chunks and the final response as a dictionary.
    """
    logger.debug("Initiating custom streaming chat.")
    openai.api_key = api_key

    # Extract only the keys that are valid for the OpenAI API
    valid_keys = ['model', 'max_tokens', 'temperature', 'top_p', 'n', 'stop', 'presence_penalty', 'frequency_penalty']
    filtered_config = {k: config_dict[k] for k in valid_keys if k in config_dict}
    
    # Format the chat history for OpenAI API
    formatted_chat_history = [
        {
            "role": msg["role"], 
            "content": msg["content"]
        } 
        for msg in chat_history if not msg.get('truncated', False) or msg.get('protected', False)
    ]
    formatted_chat_history.append(
        {
            "role": "user",
            "content": query
        }
    )
    
    try:
        response = await openai.ChatCompletion.acreate(
            messages=formatted_chat_history,
            stream=True,
            **filtered_config
        )
    except Exception as e:
        # logger.error(f"API call failed: {e}")  # log in main script
        yield {"error": str(e)}
        return

    complete_response = ""
    
    try:
        async for chunk in response:
            delta = chunk.get("choices")[0].get("delta", {})
            content = delta.get("content", "")
            complete_response += content
            yield content
    except Exception as e:
        logger.error(f"API call failed: {e}")
        yield {"error": str(e)}
        return
    
    final_response = {
        "complete_message": complete_response,
        "id": chunk.get("id"),
        "created": chunk.get("created"),
        "model": chunk.get("model"),
        "finish_reason": chunk.get("choices")[0].get("finish_reason")
    }
    
    logger.debug("Yielding final response.")
    yield final_response

