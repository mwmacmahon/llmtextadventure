# Chat Conversion Scripts

This directory contains two scripts used for processing chat outputs from the main application. The scripts are designed to convert chat history into specific formats for various uses such as generating training datasets or standardizing chat history outputs. They act upon chat outputs typically saved in the `/chat_histories` directory of the main code repository.

## Scripts

### 1. `convert_to_ooba_chat_history.sh`

#### Purpose
This script converts chat histories into a structured format suitable for viewing or further processing. It segregates messages into internal and visible conversations, with the ability to tag system messages.

#### Usage
```bash
./convert_to_ooba_chat_history.sh --input <inputfile.json> --output <outputfile.json> [--systemtag <systemtag>]
```

- `--input`: Path to the input JSON file containing the chat history.
- `--output`: Path where the converted file will be saved.
- `--systemtag` (optional): Custom tag to mark system messages. Default is `<|BEGIN-VISIBLE-CHAT|>`.

#### Requirements
- `jq`: This script requires the `jq` command-line JSON processor.

#### Output
The script outputs a JSON file with conversations categorized into `internal` and `visible` sections. The output is saved in the `/conversion_outputs` directory.

### 2. `convert_to_training_dataset.sh`

#### Purpose
This script is designed to convert chat histories into formats suitable for training machine learning models. It supports multiple output formats and includes an option to add instructional messages.

#### Usage
```bash
./convert_to_training_dataset.sh (--input <inputfile.json> | --input-dir <inputdirectory>) --output <outputfile> --format <format> [--instruction-message <instruction_message>]
```

- `--input` or `--input-dir`: Path to the input JSON file or directory containing multiple JSON files.
- `--output`: Path where the converted dataset will be saved.
- `--format`: Desired output format (`alpaca-raw` or `chatml-raw`).
- `--instruction-message` (optional): Custom instruction to be added to the dataset. Default message is provided.

#### Requirements
- `jq`: This script requires the `jq` command-line JSON processor.

#### Output
The script generates a dataset file in the specified format, with each conversation entry appropriately structured according to the chosen format. The output is saved in the `/conversion_outputs` directory.

## General Notes

- Ensure that the `jq` utility is installed on your system before running these scripts.
- Both scripts will provide appropriate usage messages if run with incorrect or insufficient arguments.
- The output directories (`/conversion_outputs`) should be present or should be created before running the scripts.
