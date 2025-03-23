import os
import yaml
import pkg_resources
from dataclasses import dataclass
from typing import Dict, List, Optional, Literal

@dataclass
class DockerConfig:
    """Configuration for the Docker execution environment."""
    image: str = "python:3.12.2-slim"
    working_dir: str = "/app"
    memory_limit: str = "256m"
    cpu_limit: float = 0.5
    timeout: int = 30  # seconds
    network_disabled: bool = True
    read_only: bool = True
    
@dataclass
class PackageConfig:
    """Configuration for package management."""
    installer: Literal["uv", "pip"] = "uv"
    index_url: Optional[str] = None
    trusted_hosts: List[str] = None
    
    def __post_init__(self):
        if self.trusted_hosts is None:
            self.trusted_hosts = []

@dataclass
class Configuration:
    """Main configuration for the Python Docker MCP server."""
    docker: DockerConfig = DockerConfig()
    package: PackageConfig = PackageConfig()
    allowed_modules: List[str] = None
    blocked_modules: List[str] = None
    
    def __post_init__(self):
        if self.allowed_modules is None:
            # Default safe modules
            self.allowed_modules = ["math", "datetime", "random", "json", "re", "collections"]
        
        if self.blocked_modules is None:
            # Default unsafe modules
            self.blocked_modules = ["os", "sys", "subprocess", "shutil", "pathlib"]

def get_default_config() -> Dict:
    """Load the default configuration from the embedded YAML file."""
    try:
        default_config_path = pkg_resources.resource_filename('python_docker_mcp', 'default_config.yaml')
        with open(default_config_path, 'r') as f:
            return yaml.safe_load(f)
    except (pkg_resources.DistributionNotFound, FileNotFoundError):
        # Fall back to local path for development
        current_dir = os.path.dirname(os.path.abspath(__file__))
        default_config_path = os.path.join(current_dir, 'default_config.yaml')
        try:
            with open(default_config_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            # Return empty dict if default config file not found
            return {}

def load_config(config_path: Optional[str] = None) -> Configuration:
    """Load configuration from a YAML file, with fallback to default values."""
    # Load default configuration
    default_config_data = get_default_config()
    
    # Create default configuration object
    docker_config = DockerConfig()
    package_config = PackageConfig()
    
    # Apply default config data if available
    if default_config_data:
        if "docker" in default_config_data:
            docker = default_config_data["docker"]
            for key, value in docker.items():
                if hasattr(docker_config, key):
                    setattr(docker_config, key, value)
                    
        if "package" in default_config_data:
            package = default_config_data["package"]
            for key, value in package.items():
                if hasattr(package_config, key):
                    setattr(package_config, key, value)
    
    default_config = Configuration(
        docker=docker_config,
        package=package_config,
        allowed_modules=default_config_data.get("allowed_modules"),
        blocked_modules=default_config_data.get("blocked_modules")
    )
    
    # If no custom config path provided, look in standard locations
    if not config_path:
        # Check environment variable
        config_path = os.environ.get("PYTHON_DOCKER_MCP_CONFIG")
        
        # Check user config directory
        if not config_path or not os.path.exists(config_path):
            config_dir = os.path.join(os.path.expanduser("~"), ".python-docker-mcp")
            config_path = os.path.join(config_dir, "config.yaml")
    
    # If custom config exists, apply it on top of defaults
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config_data = yaml.safe_load(f)
                
            # Parse docker configuration
            if config_data and "docker" in config_data:
                docker = config_data["docker"]
                for key, value in docker.items():
                    if hasattr(default_config.docker, key):
                        setattr(default_config.docker, key, value)
            
            # Parse package configuration
            if config_data and "package" in config_data:
                package = config_data["package"]
                for key, value in package.items():
                    if hasattr(default_config.package, key):
                        setattr(default_config.package, key, value)
            
            # Apply other settings
            if config_data and "allowed_modules" in config_data:
                default_config.allowed_modules = config_data["allowed_modules"]
                
            if config_data and "blocked_modules" in config_data:
                default_config.blocked_modules = config_data["blocked_modules"]
                
        except Exception as e:
            print(f"Error loading configuration from {config_path}: {e}")
    
    return default_config 