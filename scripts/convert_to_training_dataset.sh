#!/bin/bash

# convert_to_training_dataset.sh

# Default values
INSTRUCTION_MESSAGE="Continue the chat dialogue below. Write a single reply to the last message, but do not continue the conversation further."
FORMAT=""
INPUT_DIR=""
INPUT=""
OUTPUT=""

# Check if jq is installed
if ! command -v jq &> /dev/null
then
    echo "jq could not be found. Please install jq to run this script."
    exit 1
fi

# Ensure the script uses the repository root as the current working directory
cd "$(dirname "$0")"/..

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --input) INPUT="$2"; shift ;;
        --input-dir) INPUT_DIR="$2"; shift ;;
        --output) OUTPUT="$2"; shift ;;
        --instruction-message) INSTRUCTION_MESSAGE="$2"; shift ;;
        --format) FORMAT="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# Helper function to process input file path
process_input_path() {
    local path=$1
    if [[ "$path" != /* ]]; then
        if [[ -f "$PWD/$path" ]]; then
            echo "$PWD/$path"
        elif [[ -f "$PWD/chat_histories/$path" ]]; then
            echo "$PWD/chat_histories/$path"
        elif [[ -f "$PWD/chat_histories/$path.json" ]]; then
            echo "$PWD/chat_histories/$path.json"
        else
            echo ""
        fi
    else
        echo "$path"
    fi
}

# Helper function to process output file path
process_output_path() {
    local path=$1
    if [[ "$path" != /* ]]; then
        echo "$PWD/conversion_outputs/$path"
    else
        echo "$path"
    fi
}


# Check if input/output file and format are provided and valid
if { [[ -z "$INPUT" ]] && [[ -z "$INPUT_DIR" ]]; } || [[ -z "$OUTPUT" ]] || [[ -z "$FORMAT" ]]; then
    echo "Invalid input or output file. Please check the file paths."
    exit 1
fi

# Process input and output paths
if [[ -n "$INPUT" ]]; then
    INPUT=$(process_input_path "$INPUT")
fi
if [[ -n "$INPUT_DIR" ]]; then
    INPUT_DIR=$(process_input_path "$INPUT_DIR")
fi
OUTPUT=$(process_output_path "$OUTPUT")


# Ensure the output file exists and is empty before starting
> "$OUTPUT"

export INSTRUCTION_MESSAGE

# Function to convert to alpaca-raw format
function convert_to_alpaca_raw {
    local file=$1
    local output_file=$2
    {
        echo "Instruction: ${INSTRUCTION_MESSAGE}"
        jq_script='
            def capitalize_role:
                if . == "system" then "System"
                elif . == "user" then "User"
                elif . == "assistant" then "Assistant"
                else .
                end;

            # Using tojson to preserve escape sequences like \n, then remove the enclosing quotes
            (.conversation[] | "\((.role | capitalize_role)): \(.content)" | tojson | .[1:-1])
        '
        jq --arg INSTRUCTION_MESSAGE "$INSTRUCTION_MESSAGE" -r "$jq_script" "$file"
    } >> "$output_file"
}

# Function to convert to chatml-raw format
function convert_to_chatml_raw {
    local file=$1
    local output_file=$2
    {
        echo "<|im_start|>instruction"
        echo "${INSTRUCTION_MESSAGE}<|im_end|>"
        jq_script='
            .conversation[] | 
            "<|im_start|>" + (.role | tojson | .[1:-1]) + "\n" + (.content | tojson | .[1:-1]) + "<|im_end|>"
        '
        jq -r "$jq_script" "$file"
    } >> "$output_file"
}



# Function to process a single file
process_file() {
    local file=$1
    case $FORMAT in
        "alpaca-raw")
            convert_to_alpaca_raw "$file" "$OUTPUT"
            ;;
        "chatml-raw")
            convert_to_chatml_raw "$file" "$OUTPUT"
            ;;
        *)
            echo "Invalid format: $FORMAT"
            exit 1
            ;;
    esac
}

# Main conversion logic
if [[ -n "$INPUT" ]]; then
    # Single file processing
    process_file "$INPUT"
elif [[ -n "$INPUT_DIR" ]]; then
    # Directory processing
    # Using find with -print0 and while read loop to handle file names with spaces or special characters
    find "$INPUT_DIR" -name '*.json' -type f -print0 | while IFS= read -r -d '' file; do
        echo "Converting ${file}..."
        process_file "$file"
    done
    # # OLD: Using a for loop to handle file names more robustly
    # for file in $(find "$INPUT_DIR" -name '*.json' -type f); do
    #     echo $file
    #     process_file "$file"
    # done
fi


if [ $? -ne 0 ]; then
    echo "Conversion failed."
    exit 1
else
    echo "Conversion completed. Output file is $OUTPUT."
fi
