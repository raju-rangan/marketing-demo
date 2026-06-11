import os
import logging

def get_logger(name: str):
    # Absolute path to marketing-agent/mcp.log
    log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "mcp.log")
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Avoid duplicate handlers if logger is re-initialized
    if not logger.handlers:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s"))
        logger.addHandler(file_handler)
        
        # Also print to stderr
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(stream_handler)
        
    return logger

import sys
