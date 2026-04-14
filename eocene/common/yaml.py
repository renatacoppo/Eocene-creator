# function to read yaml configuration file
import yaml
from pathlib import Path

def load_yaml(infile):
    """
    Load and parse a YAML configuration file.

    Args:
        infile (str | Path): Path to the YAML file.

    Returns:
        dict: Parsed YAML content.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the file cannot be parsed as valid YAML.
        ValueError: If the YAML content is empty or invalid.
    """
    path = Path(infile)

    if not path.is_file():
        raise FileNotFoundError(f"[YAML Loader] File not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"[YAML Loader] Failed to parse YAML file {path}: {e}")

    if data is None:
        raise ValueError(f"[YAML Loader] Parsed YAML file is empty: {path}")

    return data