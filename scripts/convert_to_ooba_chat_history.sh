#!/bin/bash

# convert_chat_history.sh

# Default value for system message tag
SYSTEM_MESSAGE="<|BEGIN-VISIBLE-CHAT|>"

# Check if jq is installed
if ! command -v jq &> /dev/null
then
    echo "jq could not be found. Please install jq to run this script."
    exit 1
fi

# Ensure the script uses the repository root as the current working directory
cd "$(dirname "$0")"/..

# Initialize variables for input and output files
INPUT=""
OUTPUT=""

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --input) INPUT="$2"; shift ;;
        --output) OUTPUT="$2"; shift ;;
        --systemtag) SYSTEM_MESSAGE="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# Function to handle input file path
process_input_path() {
    local path=$1
    # Check if the path is absolute
    if [[ "$path" != /* ]]; then
        # Try current directory/user input
        if [[ -f "$PWD/$path" ]]; then
            echo "$PWD/$path"
        # Try current directory/chat_histories/user input
        elif [[ -f "$PWD/chat_histories/$path" ]]; then
            echo "$PWD/chat_histories/$path"
        # Add .json extension and try again
        elif [[ -f "$PWD/chat_histories/$path.json" ]]; then
            echo "$PWD/chat_histories/$path.json"
        else
            echo ""
        fi
    else
        echo "$path"
    fi
}

# Function to handle output file path
process_output_path() {
    local path=$1
    # Check if the path is absolute
    if [[ "$path" != /* ]]; then
        echo "$PWD/conversion_outputs/$path"
    else
        echo "$path"
    fi
}

# Process input and output paths
INPUT=$(process_input_path "$INPUT")
OUTPUT=$(process_output_path "$OUTPUT")

# Check if input and output files are provided and valid
if [[ -z "$INPUT" ]] || [[ -z "$OUTPUT" ]]; then
    echo "Invalid input or output file. Please check the file paths."
    exit 1
fi

export SYSTEM_MESSAGE
jq_script='
  def escape_html:
    gsub("&"; "&amp;") |
    gsub("<"; "&lt;") |
    gsub(">"; "&gt;") |
    gsub("\""; "&quot;") |
    gsub("\u0027"; "&#x27;");

  # Process each conversation entry
  def process_conversation:
    .conversation | reduce .[] as $item ([]; 
      if $item.role == "system" then 
        . + [[env.SYSTEM_MESSAGE, ($item.content | escape_html)]]
      elif $item.role == "user" or $item.role == "assistant" then 
        if .[-1] | length == 1 then 
          .[-1] += [$item.content | escape_html]
        else 
          . + [[$item.content | escape_html]]
        end 
      else 
        .
      end
    );

  # Build the final structure
  {
    internal: process_conversation | map(select(length == 2)),
    visible: process_conversation | map(select(length == 2))
  }
'

# Execute the jq command with the script
jq --arg SYSTEM_MESSAGE "$SYSTEM_MESSAGE" -r "$jq_script" "$INPUT" > "$OUTPUT"

if [ $? -ne 0 ]; then
    echo "Conversion failed."
    exit 1
else
    echo "Conversion completed. Output file is $OUTPUT."
fi
