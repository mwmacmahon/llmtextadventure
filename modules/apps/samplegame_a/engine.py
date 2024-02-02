
from pydantic import BaseModel, ValidationError, model_validator, field_validator
from typing import Optional, TypeVar, Type, Tuple
import re
from modules.core.config import BaseConfig
from modules.apps.samplegame_a.patterns import SampleGameAConfig, SampleGameAState
from modules.core.engine import ConversationEngine
from modules.core.patterns import Config, State

from modules.apps.samplegame_a.helpers import update_time

# Initialize console logging
import logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class SampleGameAEngine(ConversationEngine):
    """
    Controls the flow and logic of the conversation/game, interfacing between the user 
    and the LLM. It handles loading and updating the conversation/game state, interpreting 
    user inputs, generating appropriate prompts for the LLM and updating the state based 
    on the user and LLM's outputs. It integrates with various managers to process input, 
    manage state, and apply transformations.

    Does not use schema, as it is not a configuration class. Instead, the config_class
    and state_class attributes are used to determine the base classes and schemas for the 
    config and state attributes. As such, subclasses do not need to touch __init__().

    Attributes:
        [Inherited from ConversationEngine] config, state, llm_manager, transformation_manager, parsing_manager
        config_class (Type[Config]): Default class for the configuration 
        state_class (Type[State]): Default class for the state
    """
    # [Inherited from ConversationEngine] config, state, llm_manager, transformation_manager, parsing_manager
    config_class: Type[Config] = SampleGameAConfig
    state_class: Type[State] = SampleGameAState

    ## Init kept from base class - will use the config and state classes defined above
    ## and as such will use the schemas referenced in those classes


    async def query(self, user_input: str):
        """
        Processes the user input, generates the LLM prompt, and updates the conversation history.

        Args:
            user_input (str): The user input text.

        Yields:
            Partial or complete responses from the LLM.
        """
        # Process user input and update state
        self.state, processed_user_input, user_flag_response = await self.process_user_input(user_input)


        # If the processed user input results in immediate flags response, return this response
        # and do not continue with the LLM cycle
        if user_flag_response:
            if len(processed_user_input) == 0:
                # If the user input was only a special command, return the response
                yield {
                    "status": "finished",  # signals that the response is complete
                    "message": user_flag_response
                }
            else:
                # Yield the user response but still send
                # the remaining user input to the LLM
                yield {
                    "status": "running",  # signals more response data is coming
                    "message": user_flag_response
                }


        # If no immediate response is needed, continue with the LLM cycle
        llm_prompt = await self.generate_llm_prompt(processed_user_input)
        llm_output = await self.llm_manager.generate_response(llm_prompt, self.state.llm_io_history, prefix=None)
        llm_output_text = llm_output  # in case output becomes more than the text, can edit this


        # Process LLM output and generate response
        self.state, processed_llm_output =  await self.process_llm_output(llm_output_text, processed_user_input)
        response = await self.generate_response(llm_output_text, processed_user_input)



        # Add both user input and output to chat history
        await self.add_message_to_history("user", user_input, llm_prompt)
        await self.add_message_to_history("assistant", response, llm_output_text)

        # Truncate the chat history as needed
        await self.truncate_chat_history()


        # Save to output file if specified
        if self.output_path:
            if self.output_path.endswith(".json"):
                await self.save_json(self.output_path)
            elif self.output_path.endswith(".yml"):
                await self.save_yaml(self.output_path)
            else:
                raise ValueError(f"Invalid output file type: {self.output_path}. Valid values are .json and .yml")

        # Return a message signaling the response and processing is complete
        yield {
            "status": "finished",
            "message": response
        }


    async def process_user_input(self, user_input: str) -> Tuple[SampleGameAState, Optional[str]]:
        new_state = self.state.model_copy(deep=True)
        processed_input, flags_updated = parse_and_update_for_special_commands(user_input, new_state)
        response_for_flags = generate_response_for_flags(new_state) if flags_updated else None
        return new_state, processed_input, response_for_flags


    # async def process_user_input(self, user_input: str) -> Tuple[State, Optional[str]]:
    #     """
    #     Process the user input, parsing and transforming it based on the Config
    #     and updating the current state based as dictated by the parsing functions.

    #     If it returns None for the processed input, the ConversationManager should
    #     not send anything to the LLM, but instead process the situational flags
    #     and ask the user for more input.
    #     """
    #     # Copy the current state for modifications
    #     new_state = self.state.model_copy(deep=True)

    #     # Define special command patterns
    #     special_commands = {
    #         "<<display inventory>>": "display_inventory",
    #         # Add more patterns and corresponding flags here
    #     }

    #     # Initialize processed_input
    #     processed_input = user_input

    #     # Loop over special commands and process them
    #     for command, flag in special_commands.items():
    #         if command in user_input:
    #             # Add the flag to the situational flags
    #             new_state.situational_flags.append(flag)

    #             # Remove the command from the input
    #             processed_input = re.sub(re.escape(command), '', processed_input).strip()

    #     # Check if the remaining text is empty
    #     if not processed_input:
    #         return new_state, None

    #     # Return the updated state and processed input
    #     return new_state, processed_input

    async def handle_user_flags(self) -> Tuple[State, Optional[str]]:
        """
        Process the situational flags, updating the state and generating a response
        to the user based on the flags.  Returns None for a response if
        no actionable flags are found.

        If it returns None for the response, the ConversationManager should
        not send anything to the LLM, but instead ask the user for more input.
        """
        # Copy the current state for modifications
        new_state = self.state.model_copy(deep=True)

        # Initialize response elements
        flag_found = False
        resource_list = ""
        inventory_list = ""

        # Check for 'display resources' flag
        if "display_resources" in new_state.situational_flags:
            print("Printing resources")
            print(f"{new_state.situational_flags}")
            resource_list = "Resources:\n" + "\n".join(
                f"- {resource['name']}: {resource['level']}" 
                for resource in new_state.resources
            )
            new_state.situational_flags.remove("display_resources")
            print(f"{new_state.situational_flags}")
            flag_found = True

        # Check for 'display inventory' flag
        if "display_inventory" in new_state.situational_flags:
            print("Printing inventory")
            print(f"{new_state.situational_flags}")
            inventory_list = "Inventory:\n" + "\n".join(
                f"- {item['name']}" for item in new_state.inventory
            )
            new_state.situational_flags.remove("display_inventory")
            print(f"{new_state.situational_flags}")
            flag_found = True

        if flag_found:
            # Combine elements for response
            user_flags_response = (
                "-----------------------------------------\n"
                + (resource_list + "\n\n" if resource_list else "")
                + (inventory_list + "\n\n" if inventory_list else "")
                + "\n-----------------------------------------"
            )

            # Return the updated state and text response to user based on flags
            return new_state, user_flags_response
        else:
            return new_state, None  # No flags found, return None for response


    async def generate_llm_prompt(self, processed_input: str) -> str:
        """
        Given the user input, assemble the prompt to send to the LLM.
        """
        # Start with the universal first prompt
        prompt = self.config.universal_first_prompt

        # Add the user input
        prompt += f"\nUser input: {processed_input}\n"

        # Add the universal post-input prompt
        prompt += self.config.universal_post_input_prompt

        # Process situational flags
        for flag in self.state.situational_flags.copy():
            for situational_prompt in self.config.situational_prompts:
                if flag == situational_prompt['flag']:
                    prompt += f"\n{situational_prompt['prompt_text']}\n"
                    self.state.situational_flags.remove(flag)

        # Return the constructed prompt
        return prompt


    async def process_llm_output(self, llm_output: str, processed_user_input: str) ->  Tuple[SampleGameAState, str]:
        # print("TEST - process_llm_output()")
        logger.debug("TEST - process_llm_output()")
        new_state = self.state.model_copy(deep=True)
        new_state = parse_and_update_state_from_llm_output(llm_output, new_state)
        return new_state, llm_output

    # async def process_llm_output(self, llm_output: str, user_input: str) -> Tuple[State, str]:
    #     """
    #     Process the LLM output, parsing and transforming it based on the Config
    #     and updating the current state based as dictated by the parsing functions.
    #     """
    #     new_state = self.state.model_copy(deep=True)

    #     # Parsing and updating elapsed time
    #     time_pattern = r"<<Elapsed time: (\d{1,2}):(\d{2})>>"
    #     time_matches = re.finditer(time_pattern, llm_output)
    #     for match in time_matches:
    #         hours, minutes = map(int, match.groups())
    #         new_state.time = update_time(new_state.time, hours_passed=hours, minutes_passed=minutes)

    #     # Parsing and updating inventory
    #     inventory_pattern = r"<<(Added|Removed) from inventory: (.*?)>>"
    #     inventory_matches = re.finditer(inventory_pattern, llm_output)
    #     for match in inventory_matches:
    #         action, item = match.groups()
    #         if action.lower() == 'added':
    #             new_state.inventory.append({'name': item})
    #         elif action.lower() == 'removed':
    #             new_state.inventory = [i for i in new_state.inventory if i['name'] != item]

    #     # Parsing and updating resource quantities
    #     resource_pattern = r"<<Resource quantity changed for (.*?): ([+-]?\d+\.?\d*)>>"
    #     resource_matches = re.finditer(resource_pattern, llm_output)
    #     for match in resource_matches:
    #         resource_name, change = match.groups()
    #         change = float(change)
    #         for resource in new_state.resources:
    #             if resource['name'].lower() == resource_name.lower():
    #                 resource['level'] += change
    #                 break

    #     return new_state, llm_output

    async def generate_response(self, llm_output: str, user_input: str) -> str:
        """
        Given the llm response and user input, assemble the final
        message sent back to the user. May use the self.state.___
        in order to display information about the conversation
        in subclasses.
        """
        response = f"""{llm_output}
        End time: {self.state.time}
        """
        return response


## HELPERS, refactor to helpers.py later 


def update_resources(game_state, message):
    pattern = r"<<Resource: (\w+) ([+-]\d+)>"
    match = re.search(pattern, message)
    if match:
        resource_name, change = match.groups()
        change = int(change)

        # Check if the resource exists in the game state
        if resource_name in game_state['resources']:
            game_state['resources'][resource_name] += change

    ## Raise errors instead?
        # else:
        #     return "Error: Resource not found"
    # return "Error: No valid update found in message"
    return game_state


def update_character_facts(game_state, message):
    pattern = r"<<New Fact for Crewmate (\w+): (.+?)>>"
    match = re.search(pattern, message)
    if match:
        character_name, fact = match.groups()

        # Check if the character exists in the game state
        if character_name in game_state['characters']:
            if 'facts' not in game_state['characters'][character_name]:
                game_state['characters'][character_name]['facts'] = []
            game_state['characters'][character_name]['facts'].append(fact)

    ## Raise errors instead?
        # else:
        #     return "Error: Character not found"
    # return "Error: No valid update found in message"

    return game_state


def parse_and_update_for_special_commands(user_input: str, state: SampleGameAState) -> Tuple[str, bool]:
    special_commands = {
        "<<display inventory>>": lambda s: s.display_inventory_flag(),
        "<<display resources>>": lambda s: s.display_resources_flag(),
        # Additional special commands and their corresponding functions
    }

    flags_updated = False
    for command, action in special_commands.items():
        if command in user_input:
            action(state)  # Execute the action associated with the command
            user_input = user_input.replace(command, "").strip()
            flags_updated = True

    return user_input, flags_updated

def generate_response_for_flags(state: SampleGameAState) -> str:
    responses = []

    if state.display_inventory_flag:
        inventory_list = "\n".join(f"- {item['name']}" for item in state.inventory)
        responses.append(f"Inventory:\n{inventory_list}")
        state.display_inventory_flag = False

    if state.display_resources_flag:
        resource_list = "\n".join(f"- {resource['name']}: {resource['level']}" for resource in state.resources)
        responses.append(f"Resources:\n{resource_list}")
        state.display_resources_flag = False

    return "\n\n".join(responses)

def generate_prompt_for_situational_flags(state: SampleGameAState) -> str:
    prompt_parts = []

    if state.needs_clarification_flag:
        prompt_parts.append("<<Seeking Clarification>> Please clarify your last action.")
        state.needs_clarification_flag = False

    # Additional checks for other flags and corresponding prompt additions

    return "\n".join(prompt_parts)

def parse_and_update_state_from_llm_output(llm_output: str, state: SampleGameAState):
    # Utilize the earlier provided functions like update_resources and update_character_facts
    # print("TEST - parse_and_update_state_from_llm_output()")
    logger.debug("TEST - parse_and_update_state_from_llm_output()")

    # TODO: introduce if/else or try/except logic to handle issues
    state = update_resources(state, llm_output)
    state = update_character_facts(state, llm_output)
    # Additional parsing and updating based on LLM output

    return state



