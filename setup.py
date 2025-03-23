from setuptools import setup

setup(
    name="python-docker-mcp",
    version="0.1.0",
    description="Dockerised Python execution environment",
    author="Shannon Sands",
    author_email="shannon.sands.1979@gmail.com",
    packages=["python_docker_mcp"],
    package_dir={"": "src"},
    python_requires=">=3.11",
    install_requires=[
        "docker>=7.1.0",
        "mcp>=1.5.0",
        "pyyaml>=6.0.2",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-cov>=4.1.0",
            "pytest-asyncio>=0.23.0",
            "pytest-mock>=3.11.1",
            "pre-commit>=3.4.0",
            "black>=23.7.0",
            "isort>=5.12.0",
            "flake8>=6.1.0",
            "mypy>=1.5.1",
            "types-PyYAML>=6.0.12.11",
        ],
    },
) 