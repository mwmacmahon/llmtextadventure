"""
This file contains miscellaneous helper functions.
"""

import os
import yaml
import json
from typing import Dict


# Initialize console logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_filename_without_extension(input_filepath):
    """
    Returns the filename without the extension from the given input filepath.

    Args:
        input_filepath (str): The input filepath.

    Returns:
        str: The filename without the extension.
    """
    # Extract the base name (e.g., 'file.txt' from '/path/to/file.txt')
    base_name = os.path.basename(input_filepath)

    # Split the base name into the file name and extension, and return just the file name
    file_name_without_extension, _ = os.path.splitext(base_name)

    return file_name_without_extension

def load_yaml(file_path: str) -> Dict:
    """
    Loads and returns the configuration data from a YAML file.

    Args:
        file_path (str): The file path of the YAML configuration file.

    Returns:
        Dict: A dictionary containing the loaded configuration data.
    """
    try:
        with open(file_path, 'r') as file:
            config_data = yaml.safe_load(file)
            return config_data
    except FileNotFoundError:
        raise FileNotFoundError(f"The configuration file '{file_path}' was not found.")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error occurred while parsing YAML file: {e}")

def load_json(file_path: str) -> Dict:
    """
    Loads and returns the data from a JSON file.

    Args:
        file_path (str): The file path of the JSON file.

    Returns:
        Dict: A dictionary containing the loaded data.
    """
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
            return data
    except FileNotFoundError:
        raise FileNotFoundError(f"The file '{file_path}' was not found.")
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"Error occurred while parsing JSON file: {e}")
    
def save_json(data: Dict, file_path: str):
    """
    Saves the given data to a JSON file.

    Args:
        data (Dict): The data to be saved.
        file_path (str): The file path of the JSON file.
    """
    with open(file_path, 'w') as file:
        json.dump(data, file, indent=4)

def save_yaml(data: Dict, file_path: str):
    """
    Saves the given data to a YAML file.

    Args:
        data (Dict): The data to be saved.
        file_path (str): The file path of the YAML file.
    """
    with open(file_path, 'w') as file:
        yaml.dump(data, file, default_flow_style=False)