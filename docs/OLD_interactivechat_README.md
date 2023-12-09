# Interactive OpenAI Chat Assistant

The Interactive OpenAI Chat Assistant is a tool designed to facilitate real-time conversations with OpenAI's GPT models. The primary goal is to allow users to either start with an existing conversation base or profile and seamlessly continue the dialogue. Recorded conversations can be resumed, making it ideal for retaining context or serving as valuable training data for future model fine-tuning.

## Features

- **Profile-Based Conversations**: Begin your chat with an existing profile, which might just be a system prompt or a detailed history.
- **Interactive Real-time Chat**: Experience real-time interactions with OpenAI's model, just like you're having a chat with a human.
- **Resume Conversations**: Never lose context. Pick up right where you left off from a previous session.
- **Training Data Collection**: Record interactions for potential use as training data or analysis later on.

## How it Works

1. **Setup**: The program reads from configuration files, environment variables, and command-line arguments to get started.
2. **Displaying Previous Interactions**: If provided, the tool will first display previous interactions to give the user context.
3. **Interactive Session**: The user can interact in real-time with the model. The interactions are streamed to and from OpenAI's servers, offering a near-instant response experience.
4. **Session Termination**: At any point, the user can decide to end the session. The entire chat history is saved for future reference or continuation.

## Usage

1. **Initial Setup**:
   - Ensure Python 3.8 or newer is installed.
   - Install the necessary libraries using `pip install openai asyncio python-dotenv pyyaml`.
   - Set up your `.env` file in the root directory with the format `OPENAI_API_KEY=your_api_key_here`.

2. **Running the Program**:

   - Start the chat:
     ```
     python main.py --input basic_profile.json
     ```
     This will initiate the chat using the `basic_profile.json` profile. If you don't provide an input file, the program will prompt you for one or use the default specified in `config.yml`. The input can be a profile (set of config parameter and system chat prompt), or a previous conversation history. You can create your own profile or invented chat history by making an new .json file in the chat_histories directory.

   - Specify both input and output files:
     ```
     python main.py --input basic_profile.json --output mychat_20230924.json
     ```
     This will save the interaction in `mychat_20230924.json`.

   - Simply starting the program without any arguments will rely on the `config.yml` defaults and interactive prompts:
     ```
     python main.py
     ```

3. **Profile File Structure**:

   Here's a simple example of what a profile (like `basic_profile.json`) might look like:

   ```json
   {
     "conversation": [
       {
         "role": "system",
         "content": "You are a helpful assistant."
       },
       {
         "role": "user",
         "content": "What's the capital of France?"
       },
       {
         "role": "assistant",
         "content": "The capital of France is Paris."
       }
     ],
     "configuration": {
       "temperature": 0.8,
       "max_response_tokens": 150
     }
   }
